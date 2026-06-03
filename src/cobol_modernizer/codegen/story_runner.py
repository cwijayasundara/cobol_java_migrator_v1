"""Story runner orchestration (Task 6 of the story-sliced codegen engine).

The runnable checkpoint that sequences Tasks 1-5 for ONE story at a time, and
`run_story_plan` to iterate a whole `StoryCodegenPlan` in dependency order. The
lifecycle for each story is legible top-to-bottom:

    resume? -> generate tests -> write -> targeted mvn (RED baseline)
            -> generate impl -> write -> targeted mvn (GREEN)
            -> bounded repair (impl re-gen on the failing log) -> gate -> persist

GATE (decide the recorded status):
  - `passed`              : every AC id cited in tests AND tests GREEN AND files
                            carry the story id + cobol lineage.
  - `generated_unverified`: AC-citation + lineage hold but the toolchain was
                            unavailable (mvn absent) — accepted-but-unverified.
  - `failed`              : tests still red after the repair budget, OR AC
                            coverage incomplete, OR lineage missing.

This module makes the FOUR heavy dependencies INJECTABLE (LLM test-gen, LLM
impl-gen, the Maven run, the clock) so unit tests stub them; it has NO direct
Neo4j / LLM / Maven calls of its own. The caller (Task 7/9) builds the slice pack
and scaffolds the module and hands BOTH in — the runner receives an already-built
`context_pack` and an already-scaffolded `module_dir` so it stays unit-testable
without Neo4j. Telemetry is snapshotted as deltas around the story's LLM calls off
the injected runner's `.token_usage`/`.cost_usd`; wall time uses an injectable
`now` clock (default `time.monotonic`) so tests stay deterministic.
"""
from __future__ import annotations

import inspect
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from cobol_modernizer.agent.harness import AgentRunner
from cobol_modernizer.codegen.budget import (
    StoryBudget, should_skip as budget_should_skip, story_budget_from_env,
)
from cobol_modernizer.codegen.patch_agent import (
    StoryPatch, generate_story_implementation, generate_story_tests,
    story_repair_max_attempts,
)
from cobol_modernizer.codegen.schema import GeneratedFile
from cobol_modernizer.codegen.story_context import StoryContextPack
from cobol_modernizer.codegen.story_plan import StoryCodegenItem, StoryCodegenStatus
from cobol_modernizer.codegen.story_storage import (
    get_story_record, record_story_status,
)
from cobol_modernizer.codegen.test_runner import (
    StoryTestResult, StoryTestStatus, run_targeted_tests,
)
from cobol_modernizer.controlplane.build import (
    _record_generated_test_refs, scan_generated_test_refs,
)

logger = logging.getLogger(__name__)

# Injectable seam types. The LLM passes return a StoryPatch; the Maven pass returns
# a StoryTestResult; `now` returns a monotonic float for wall-time deltas.
GenTests = Callable[..., Awaitable[StoryPatch]]
GenImpl = Callable[..., Awaitable[StoryPatch]]
RunTests = Callable[..., StoryTestResult]
Clock = Callable[[], float]


@dataclass
class StoryRunResult:
    """The outcome of running ONE story: its decided status plus the telemetry and
    traceability the caller persists. `red_status` records the pre-impl baseline so
    a reviewer can confirm the story actually started RED (TDD), and `attempts` is
    the number of impl-generation passes (1 = first pass green/decided, >1 = repaired)."""

    story_id: str
    status: StoryCodegenStatus
    test_result: StoryTestResult | None = None
    red_status: StoryTestStatus | None = None
    attempts: int = 0
    ac_covered: list[str] = field(default_factory=list)
    ac_missing: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    wall_time_s: float = 0.0
    token_usage: dict[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0
    rationale: str = ""
    skipped: bool = False


# --------------------------------------------------------------------------- #
# File I/O — mirror run_build's write pattern (dest = root / path; mkdir; write) #
# --------------------------------------------------------------------------- #
def _write_files(module_dir: Path, files: list[GeneratedFile]) -> list[str]:
    """Write generated files under the scaffolded module root, exactly as
    `run_build` does (`dest = root / f.path; mkdir parents; write_text`). Returns
    the relative paths written (for the changed_files telemetry)."""
    written: list[str] = []
    for f in files:
        dest = module_dir / f.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f.content, encoding="utf-8")
        written.append(f.path)
    return written


def _existing_java(module_dir: Path) -> list[GeneratedFile]:
    """The already-scaffolded production Java the impl pass should reuse/patch
    rather than re-scaffold. Read from the module's src/main/java tree as
    kind='main' GeneratedFiles (paths relative to the module root)."""
    main_root = module_dir / "src" / "main" / "java"
    if not main_root.is_dir():
        return []
    out: list[GeneratedFile] = []
    for path in sorted(main_root.rglob("*.java")):
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        out.append(GeneratedFile(
            path=str(path.relative_to(module_dir)), kind="main", content=content))
    return out


_PUBLIC_CLASS = re.compile(r"public\s+(?:final\s+)?class\s+(\w+)")


def _test_classes(files: list[GeneratedFile]) -> str:
    """The comma-joined test-class names for a `-Dtest=` targeted run (Maven accepts a
    comma list). The token is parsed from the test file CONTENT's public class name —
    NOT the file stem — because `-Dtest=` matches the Java class, and a `FooTests.java`
    holding `class FooTest` would otherwise target a non-existent class and read as
    `no_tests_run` forever. Falls back to the file stem when no `public class` is found
    (e.g. a package-private test class). Empty string when there are no test files."""
    names: list[str] = []
    for f in files:
        if f.kind != "test":
            continue
        m = _PUBLIC_CLASS.search(f.content)
        name = m.group(1) if m else Path(f.path).stem
        if name and name not in names:
            names.append(name)
    return ",".join(names)


# --------------------------------------------------------------------------- #
# Lineage / AC gates                                                          #
# --------------------------------------------------------------------------- #
def _cites_lineage(files: list[GeneratedFile], *, story_id: str,
                   cobol_refs: list[str]) -> bool:
    """Generated production files must cite the story id AND at least one cobol ref
    (in evidence or content). When the story declares no cobol_refs the lineage
    requirement collapses to the story-id citation. No production files -> no
    lineage (a story that generated zero main files cannot have passed)."""
    mains = [f for f in files if f.kind == "main"]
    if not mains:
        return False
    blob = "\n".join(f.content + "\n" + "\n".join(f.evidence) for f in mains)
    if story_id and story_id not in blob:
        return False
    refs = [r for r in cobol_refs if r]
    if not refs:
        return True
    return any(r in blob for r in refs)


# --------------------------------------------------------------------------- #
# Resume — DELEGATES to the single source of truth (`budget.should_skip`)       #
# --------------------------------------------------------------------------- #
def _should_skip(session, *, workspace_id: str, item: StoryCodegenItem,
                 context_hash: str) -> bool:
    """Skip an already-accepted story whose context is unchanged. This function does
    ONLY the I/O (load the prior `story_codegen_status` record); the actual policy —
    accepted-status set + unchanged-hash check — lives in `budget.should_skip`, the
    single source of truth shared with the build gate (Task 10). The accepted set is
    now `passed / generated-unverified / skipped` (was `passed / generated-unverified`),
    matching `build_stories._gate_stage`."""
    prior = get_story_record(session, workspace_id, item.story_id)
    return budget_should_skip(prior, context_hash)


# --------------------------------------------------------------------------- #
# Repair                                                                      #
# --------------------------------------------------------------------------- #
#: Statuses the repair loop must NOT retry. `ok` is done; `toolchain_unavailable`
#: (mvn absent) and `error` (timeout/OSError) are INFRA problems a regenerated impl
#: cannot fix — retrying just burns the LLM budget.
_NON_REPAIRABLE = frozenset({
    StoryTestStatus.ok,
    StoryTestStatus.toolchain_unavailable,
    StoryTestStatus.error,
})


def _repair_feedback(result: StoryTestResult, touched_files: list[str]) -> dict:
    """The failing gate + bounded log excerpt + the files the previous attempt wrote,
    mirroring `repair_loop.py::run_repair_loop`'s feedback shape. A `no_tests_run`
    gate gets an explicit note: the targeted `-Dtest=` class matched ZERO tests, so
    the fix is the TEST class name, not the impl — otherwise a reviewer reading the
    log is misled into thinking the production code is still red."""
    log = result.log_excerpt
    if result.status == StoryTestStatus.no_tests_run:
        log = ("NOTE: the targeted test class matched zero tests — the generated "
               "test class name likely does not match what was run; check the test "
               "class name (regenerating the impl will not fix this).\n") + log
    return {"failing_gate": result.status.value,
            "log_excerpt": log,
            "touched_files": touched_files}


# --------------------------------------------------------------------------- #
# Telemetry                                                                   #
# --------------------------------------------------------------------------- #
def _usage_snapshot(runner: Any) -> dict[str, int]:
    return dict(getattr(runner, "token_usage", {}) or {})


def _usage_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    keys = set(before) | set(after)
    return {k: int(after.get(k, 0)) - int(before.get(k, 0)) for k in keys}


def _test_summary(result: StoryTestResult | None) -> dict[str, Any]:
    if result is None:
        return {"status": None, "failing_tests": []}
    return {"status": result.status.value,
            "failing_tests": list(result.failing_tests)}


# --------------------------------------------------------------------------- #
# Per-story lifecycle                                                         #
# --------------------------------------------------------------------------- #
async def run_story(
    item: StoryCodegenItem,
    *,
    session,
    workspace_id: str,
    module_dir: Path,
    context_pack: StoryContextPack,
    runner: AgentRunner,
    model: str = "sonnet",
    project_index: list[str] | None = None,
    gen_tests: GenTests = generate_story_tests,
    gen_impl: GenImpl = generate_story_implementation,
    run_tests: RunTests = run_targeted_tests,
    now: Clock = time.monotonic,
    repair_max_attempts: int | None = None,
    budget: StoryBudget | None = None,
    persist: bool = True,
) -> StoryRunResult:
    """Run ONE story context->tests(red)->impl->tests(green)->repair->gate->persist.

    The four heavy dependencies are injectable: `gen_tests`/`gen_impl` (LLM),
    `run_tests` (Maven), and `now` (clock). The runner receives an already-built
    `context_pack` and an already-scaffolded `module_dir` (it does NOT build the
    slice pack or scaffold). Returns a `StoryRunResult`; when `persist` is True the
    result is written via story_storage AND `generated_test_refs` is (re)recorded so
    the Verify story-behavior gate keeps reading it.
    """
    if repair_max_attempts is None:
        repair_max_attempts = story_repair_max_attempts()
    if budget is None:
        budget = story_budget_from_env()
    project_index = project_index or []
    context_hash = context_pack.context_hash

    # 1. Resume — skip an already-accepted story whose context is unchanged.
    if _should_skip(session, workspace_id=workspace_id, item=item,
                    context_hash=context_hash):
        logger.info("story %s: skipped (accepted + unchanged context_hash)",
                    item.story_id)
        return StoryRunResult(story_id=item.story_id,
                              status=StoryCodegenStatus.skipped, skipped=True)

    started = now()
    usage_before = _usage_snapshot(runner)
    cost_before = float(getattr(runner, "cost_usd", 0.0) or 0.0)

    def _telemetry() -> tuple[float, dict[str, int], float]:
        return (now() - started,
                _usage_delta(usage_before, _usage_snapshot(runner)),
                float(getattr(runner, "cost_usd", 0.0) or 0.0) - cost_before)

    try:
        # 2. Generate the FAILING tests, then write them into the scaffold.
        tests_patch = await gen_tests(
            runner=runner, item=item, context_pack=context_pack,
            project_index=project_index, model=model)
        test_files = list(tests_patch.files)
        _write_files(module_dir, test_files)
        target = _test_classes(test_files)

        # 3. Targeted run #1 — the RED baseline. Red here is EXPECTED (compile gap /
        #    failing / no_tests_run), not a story failure; we only record it.
        red = run_tests(module_dir, target)
        logger.info("story %s: red baseline status=%s",
                    item.story_id, red.status.value)

        # 4. Generate the implementation, write it, then re-run (expect GREEN).
        impl_patch = await gen_impl(
            runner=runner, item=item, context_pack=context_pack,
            failing_tests=test_files, existing_java=_existing_java(module_dir),
            model=model)
        impl_files = list(impl_patch.files)
        changed = _write_files(module_dir, impl_files)
        attempts = 1
        result = run_tests(module_dir, target)

        # 5. Bounded repair — while not green and within budget, re-generate the impl
        #    from the failing log excerpt + the touched files (mirrors
        #    run_repair_loop's feedback shape), re-write, re-run. Some statuses are
        #    NON-REPAIRABLE: a regenerated impl cannot fix a missing toolchain or an
        #    infra error (timeout/OSError) — re-running would just burn the whole LLM
        #    budget — so we break out. The attempt cap bounds the COUNT of gen calls
        #    and the per-call timeout bounds each one, but only the cost budget bounds
        #    cumulative token SIZE — consult it before each (expensive) repair gen and
        #    stop early if this story has already run away.
        over_budget = False
        while (result.status not in _NON_REPAIRABLE
               and attempts < repair_max_attempts + 1):
            wall, tok, _ = _telemetry()
            if budget.exceeded(tokens_used=sum(tok.values()), wall_s=wall):
                over_budget = True
                logger.info(
                    "story %s: over budget (tokens=%d wall=%.2fs) — stopping before "
                    "repair attempt %d", item.story_id, sum(tok.values()), wall,
                    attempts)
                break
            logger.info("story %s: repair attempt %d (gate=%s)",
                        item.story_id, attempts, result.status.value)
            impl_patch = await gen_impl(
                runner=runner, item=item, context_pack=context_pack,
                failing_tests=test_files, existing_java=_existing_java(module_dir),
                model=model,
                repair_feedback=_repair_feedback(result, changed))
            impl_files = list(impl_patch.files)
            changed = _write_files(module_dir, impl_files)
            attempts += 1
            result = run_tests(module_dir, target)
    except Exception as exc:  # noqa: BLE001 — a single bad story must not abort the
        # plan or leave NO durable trace. Record a `failed` outcome (with the error in
        # the rationale) and return; never re-raise. Half-applied files on the shared
        # module_dir are tolerated — they are overwritten/cleaned by the next run.
        logger.error("story %s: aborted with %s: %s",
                     item.story_id, type(exc).__name__, exc, exc_info=True)
        wall, token_usage, cost = _telemetry()
        out = StoryRunResult(
            story_id=item.story_id, status=StoryCodegenStatus.failed,
            wall_time_s=wall, token_usage=token_usage, cost_usd=cost,
            rationale=f"error: {exc}")
        if persist:
            _persist(session, workspace_id=workspace_id, item=item, out=out,
                     model=model, context_hash=context_hash, module_dir=module_dir)
        return out

    # 6. GATE — decide the recorded status from AC coverage + lineage + test result.
    ac_covered = scan_generated_test_refs(module_dir, item.acceptance_criteria_ids)
    ac_missing = sorted(set(item.acceptance_criteria_ids) - set(ac_covered))
    ac_ok = not ac_missing
    lineage_ok = _cites_lineage(impl_files, story_id=item.story_id,
                                cobol_refs=item.cobol_refs)

    status = _decide_status(result=result, ac_ok=ac_ok, lineage_ok=lineage_ok)

    wall, token_usage, cost = _telemetry()
    rationale = "; ".join(r for r in (tests_patch.rationale, impl_patch.rationale)
                          if r)
    if over_budget:
        # The repair loop stopped because the cost budget was exhausted, NOT because
        # the tests were exhaustively repaired — say so plainly so the durable record
        # doesn't read as a misleading "tests still red after the full budget".
        note = (f"stopped over budget (tokens={sum(token_usage.values())}, "
                f"wall={wall:.1f}s) before exhausting repair attempts")
        rationale = f"{note}; {rationale}" if rationale else note
    elif result.status == StoryTestStatus.error:
        # An infra error (mvn timeout/OSError), not a code defect — make that explicit
        # in the durable record so a reviewer doesn't chase a phantom code bug.
        note = f"infra error during test run: {result.log_excerpt[:200]}"
        rationale = f"{note}; {rationale}" if rationale else note
    out = StoryRunResult(
        story_id=item.story_id, status=status, test_result=result,
        red_status=red.status, attempts=attempts,
        ac_covered=ac_covered, ac_missing=ac_missing, changed_files=changed,
        wall_time_s=wall, token_usage=token_usage, cost_usd=cost,
        rationale=rationale)
    logger.info("story %s: status=%s attempts=%d ac=%d/%d wall=%.2fs",
                item.story_id, status.value, attempts, len(ac_covered),
                len(item.acceptance_criteria_ids), wall)

    if persist:
        _persist(session, workspace_id=workspace_id, item=item, out=out,
                 model=model, context_hash=context_hash, module_dir=module_dir)
    return out


def _decide_status(*, result: StoryTestResult, ac_ok: bool,
                   lineage_ok: bool) -> StoryCodegenStatus:
    """Map a finished story to its recorded status. AC-citation + lineage gate ALL
    outcomes. Only when both hold does the test result decide: GREEN -> passed;
    toolchain absent -> generated_unverified; an infra `error` (timeout/OSError) ->
    failed (a real failure, just not a code defect — see the rationale); anything
    else still red -> failed."""
    if not (ac_ok and lineage_ok):
        return StoryCodegenStatus.failed
    if result.status == StoryTestStatus.ok:
        return StoryCodegenStatus.passed
    if result.status == StoryTestStatus.toolchain_unavailable:
        return StoryCodegenStatus.generated_unverified
    return StoryCodegenStatus.failed


def _persist(session, *, workspace_id: str, item: StoryCodegenItem,
             out: StoryRunResult, model: str, context_hash: str,
             module_dir: Path) -> None:
    """Persist the story's outcome + telemetry as a `story_codegen_status` artifact,
    AND (re)record `generated_test_refs` (scanning the actual module dir) so the
    Verify story-behavior gate still reads it (reusing build.py's writer — never
    duplicated here)."""
    tu = out.token_usage
    payload = {
        "status": out.status.value,
        "wall_time_s": out.wall_time_s,
        "model": model,
        "token_usage": {"input": tu.get("input", 0), "output": tu.get("output", 0),
                        "cache_read": tu.get("cache_read", 0),
                        "cache_creation": tu.get("cache_creation", 0)},
        "cost_usd": out.cost_usd,
        "attempts": out.attempts,
        "changed_files": out.changed_files,
        "test_result": _test_summary(out.test_result),
        "ac_covered": out.ac_covered,
        "ac_missing": out.ac_missing,
        "rationale": out.rationale,
        "context_hash": context_hash,
    }
    record_story_status(session, workspace_id=workspace_id,
                        story_id=item.story_id, payload=payload)
    if item.acceptance_criteria_ids:
        _record_generated_test_refs(
            session, workspace_id=workspace_id, project_dir=module_dir,
            acceptance_criteria_ids=item.acceptance_criteria_ids)


# --------------------------------------------------------------------------- #
# Plan-level iteration                                                        #
# --------------------------------------------------------------------------- #
def _summary_line(item: StoryCodegenItem, out: StoryRunResult) -> str:
    """A short, deterministic one-liner summarizing a just-completed story, used as the
    dependency context for stories built later in the plan. Kept terse on purpose — the
    downstream pack only needs to know WHAT was built and its outcome, not the full
    telemetry."""
    return f"{item.story_id} [{out.status.value}]"


def _call_context_pack_for(
    context_pack_for: Callable[..., StoryContextPack],
    item: StoryCodegenItem, completed_summaries: list[str],
) -> StoryContextPack:
    """Invoke the caller's `context_pack_for`, threading the running
    `completed_summaries` when the callback accepts a second argument. Legacy
    single-arg callbacks (`lambda item: ...`) are still supported — they simply don't
    receive the summaries — so existing callers/tests need no change."""
    try:
        params = inspect.signature(context_pack_for).parameters
        arity = len([p for p in params.values()
                     if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)])
        accepts_varargs = any(p.kind == p.VAR_POSITIONAL for p in params.values())
    except (TypeError, ValueError):  # builtins / un-introspectable callables
        arity, accepts_varargs = 1, False
    if arity >= 2 or accepts_varargs:
        return context_pack_for(item, completed_summaries)
    return context_pack_for(item)


async def run_story_plan(
    items: list[StoryCodegenItem],
    *,
    session,
    workspace_id: str,
    module_dir: Path,
    context_pack_for: Callable[..., StoryContextPack],
    runner: AgentRunner,
    model: str = "sonnet",
    project_index: list[str] | None = None,
    gen_tests: GenTests = generate_story_tests,
    gen_impl: GenImpl = generate_story_implementation,
    run_tests: RunTests = run_targeted_tests,
    now: Clock = time.monotonic,
    repair_max_attempts: int | None = None,
) -> list[StoryRunResult]:
    """Run a plan's stories IN ORDER (the plan is already dependency-sorted by
    `build_story_codegen_plan`). The caller supplies `context_pack_for` to resolve
    each item's already-built pack (it owns the slice-pack/scaffold; the runner does
    not). Each `run_story` records that story's `generated_test_refs` against the
    shared module dir, so by the end the Verify gate sees every cited AC. A story that
    raises is recorded `failed` and does NOT abort the plan — the loop continues.

    As it iterates, the loop accumulates a running list of completed-story summaries
    (one terse line per finished story, ANY outcome) and threads it into the per-story
    context: `context_pack_for(item, completed_summaries)` when the callback accepts a
    second argument (legacy single-arg callbacks still work and just don't get them).
    This is what makes the "Completed Dependencies" pack section actually populate.
    `completed_summaries` is intentionally NOT part of the story's `context_hash` (it's
    derived run context), so threading it does not destabilize resume.

    NOTE: every story writes into the SAME `module_dir`; path-uniqueness of generated
    files across stories is the CALLER/scaffold's responsibility — a later story
    emitting an already-used path silently overwrites the earlier file."""
    results: list[StoryRunResult] = []
    completed_summaries: list[str] = []
    for item in items:
        pack = _call_context_pack_for(context_pack_for, item,
                                      list(completed_summaries))
        out = await run_story(
            item, session=session, workspace_id=workspace_id,
            module_dir=module_dir, context_pack=pack, runner=runner, model=model,
            project_index=project_index, gen_tests=gen_tests, gen_impl=gen_impl,
            run_tests=run_tests, now=now, repair_max_attempts=repair_max_attempts)
        results.append(out)
        completed_summaries.append(_summary_line(item, out))
    return results
