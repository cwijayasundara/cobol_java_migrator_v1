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

import asyncio
import inspect
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from cobol_modernizer.agent.harness import AgentRunner
from cobol_modernizer.codegen.budget import (
    BuildBudget, StoryBudget, build_budget_from_env, build_max_story_attempts,
    should_skip as budget_should_skip, story_budget_from_env,
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


#: Default fan-out width within a dependency wave. One in-flight story holds an LLM
#: test-gen + impl-gen (+ repairs) and a Maven run, so the concurrency cap bounds the
#: peak LLM/Maven load. Tunable via ``BUILD_MAX_CONCURRENCY`` (default 4); clamped to
#: >=1 so a bad env value can never deadlock the plan.
_BUILD_MAX_CONCURRENCY_DEFAULT = 4


def build_max_concurrency() -> int:
    """The per-wave fan-out width from ``BUILD_MAX_CONCURRENCY`` (default 4, min 1)."""
    raw = os.environ.get("BUILD_MAX_CONCURRENCY")
    if raw is None:
        return _BUILD_MAX_CONCURRENCY_DEFAULT
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return _BUILD_MAX_CONCURRENCY_DEFAULT


def _dependency_waves(
    items: list[StoryCodegenItem],
) -> list[list[StoryCodegenItem]]:
    """Group plan items into dependency WAVES for parallel fan-out, preserving the
    plan's input order WITHIN each wave (the plan is already topologically sorted, so
    this only partitions it):

      - wave 0  = items with no *unmet* ``depends_on`` (deps not present in the plan
                  are treated as already satisfied — they cannot be a wave member).
      - wave k  = items whose deps are all emitted in waves < k.

    A dep that points outside this plan's items is ignored (it cannot gate a wave).
    Cycles cannot starve the output: if a pass makes no progress, the remaining items
    are emitted as one final wave (input order) so every item runs exactly once."""
    known = {it.story_id for it in items}
    emitted: set[str] = set()
    remaining = list(items)
    waves: list[list[StoryCodegenItem]] = []
    while remaining:
        wave = [it for it in remaining
                if all(d in emitted for d in it.depends_on if d in known)]
        if not wave:
            # Cycle / self-reference among the rest: emit them all as a final wave so
            # the plan terminates and every story still runs once.
            wave = list(remaining)
        waves.append(wave)
        wave_ids = {it.story_id for it in wave}
        emitted |= wave_ids
        remaining = [it for it in remaining if it.story_id not in wave_ids]
    return waves


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
    runner_factory: Callable[[], AgentRunner] | None = None,
    model: str = "sonnet",
    project_index: list[str] | None = None,
    gen_tests: GenTests = generate_story_tests,
    gen_impl: GenImpl = generate_story_implementation,
    run_tests: RunTests = run_targeted_tests,
    now: Clock = time.monotonic,
    repair_max_attempts: int | None = None,
    max_concurrency: int | None = None,
    budget: StoryBudget | None = None,
    items_override: list[StoryCodegenItem] | None = None,
) -> list[StoryRunResult]:
    """Run a plan's stories in DEPENDENCY WAVES with bounded parallel fan-out
    (Fan-Out-and-Synthesize). The plan is already dependency-sorted by
    `build_story_codegen_plan`; here we partition it into waves (`_dependency_waves`):
    wave 0 = items with no unmet `depends_on`, wave k = items whose deps all landed in
    earlier waves. Each wave's stories run concurrently via `asyncio.gather`, bounded by
    a semaphore of width `max_concurrency` (default `BUILD_MAX_CONCURRENCY`, env default
    4). This is SINGLE-PASS: every story runs exactly once — the repeat-until-done outer
    loop, deferred status, and pooled budget are a separate concern handled elsewhere.

    The caller supplies `context_pack_for` to resolve each item's already-built pack (it
    owns the slice-pack/scaffold; the runner does not). Each `run_story` records that
    story's `generated_test_refs` against the shared module dir, so by the end the Verify
    gate sees every cited AC. A story that raises is recorded `failed` and does NOT abort
    the plan.

    CONCURRENCY + telemetry: each concurrent story gets its OWN runner instance (from
    `runner_factory`, defaulting to `type(runner)()`) so per-story token/cost telemetry
    is not crosstalked across stories sharing one mutable `runner`. The `runner` argument
    is retained for backward compatibility and as the factory default — it is NOT itself
    threaded into concurrent stories.

    COMPLETED SUMMARIES are computed from PRIOR WAVES ONLY: stories in the same wave do
    NOT see each other's summaries (they run concurrently, so there is no ordering among
    them); a wave-k story's pack carries every finished story from waves < k. As before,
    `context_pack_for(item, completed_summaries)` is used when the callback accepts a
    second argument (legacy single-arg callbacks still work and just don't get them).
    `completed_summaries` is intentionally NOT part of the story's `context_hash` (it's
    derived run context), so threading it does not destabilize resume.

    The returned results + per-story persistence are in the plan's deterministic order
    (waves preserve input order, and results are reassembled by story id), so downstream
    consumers see the same ordering as the old sequential path.

    NOTE: every story writes into the SAME `module_dir`; path-uniqueness of generated
    files across stories is the CALLER/scaffold's responsibility — two stories in the
    same wave emitting an already-used path race on the file."""
    if max_concurrency is None:
        max_concurrency = build_max_concurrency()
    if runner_factory is None:
        # Per-story runners default to fresh instances of the same class as `runner`
        # (no-arg constructor — matches SdkAgentRunner / the test FakeRunner).
        runner_factory = type(runner)

    # `items_override` lets the repeat-until-done OUTER loop re-run ONLY the still-failing
    # subset while reusing this single-pass wave fan-out unchanged. The results are still
    # reassembled in the (sub)list's input order.
    run_items = items if items_override is None else items_override
    waves = _dependency_waves(run_items)
    sem = asyncio.Semaphore(max(1, max_concurrency))
    by_id: dict[str, StoryRunResult] = {}
    completed_summaries: list[str] = []

    async def _run_one(item: StoryCodegenItem,
                       prior_summaries: list[str]) -> StoryRunResult:
        async with sem:
            pack = _call_context_pack_for(context_pack_for, item, prior_summaries)
            return await run_story(
                item, session=session, workspace_id=workspace_id,
                module_dir=module_dir, context_pack=pack, runner=runner_factory(),
                model=model, project_index=project_index, gen_tests=gen_tests,
                gen_impl=gen_impl, run_tests=run_tests, now=now,
                repair_max_attempts=repair_max_attempts, budget=budget)

    for wave in waves:
        # Snapshot the prior-wave summaries: stories in THIS wave all see the same
        # (frozen) list and never each other's outcomes.
        prior = list(completed_summaries)
        wave_results = await asyncio.gather(
            *(_run_one(item, list(prior)) for item in wave))
        for item, out in zip(wave, wave_results):
            by_id[item.story_id] = out
        # Append this wave's summaries (in wave/input order) for the next wave.
        completed_summaries.extend(
            _summary_line(item, by_id[item.story_id]) for item in wave)

    # Reassemble in the (run) plan's deterministic input order for downstream consumers.
    return [by_id[item.story_id] for item in run_items]


# --------------------------------------------------------------------------- #
# Repeat-until-done OUTER loop (+ pass-with-deferred + pooled budget)          #
# --------------------------------------------------------------------------- #
#: Statuses the OUTER loop treats as ACCEPTED (do not re-run). Mirrors
#: ``ACCEPTED_STORY_STATUSES`` conceptually but is expressed over the enum here:
#: passed / generated-unverified / skipped. ``failed`` is the ONLY status the outer
#: loop retries; ``deferred``/``blocked`` are terminal non-accepted (never retried).
_OUTER_ACCEPTED = frozenset({
    StoryCodegenStatus.passed,
    StoryCodegenStatus.generated_unverified,
    StoryCodegenStatus.skipped,
})


def _pool_tokens(out: StoryRunResult) -> int:
    """The total tokens a single story's run drew from the pool (sum of its usage
    delta)."""
    return sum(int(v) for v in (out.token_usage or {}).values())


def _mark_deferred(session, *, workspace_id: str, item: StoryCodegenItem,
                   out: StoryRunResult, model: str, context_hash: str,
                   module_dir: Path, reason: str) -> StoryRunResult:
    """Re-stamp a story that exhausted the outer loop's allotment as ``deferred``
    (terminal — the loop stops retrying it) and persist that. Carries the last run's
    telemetry forward and appends WHY it was deferred so the durable record is legible.
    Deferred is NOT accepted; the build gate (a later task) decides its fate. No NEW
    files are written here — `_persist` only (re)records the status + the same
    generated_test_refs scan against the shared module_dir."""
    rationale = f"deferred: {reason}"
    if out.rationale:
        rationale = f"{rationale}; {out.rationale}"
    deferred = StoryRunResult(
        story_id=out.story_id, status=StoryCodegenStatus.deferred,
        test_result=out.test_result, red_status=out.red_status,
        attempts=out.attempts, ac_covered=out.ac_covered, ac_missing=out.ac_missing,
        changed_files=out.changed_files, wall_time_s=out.wall_time_s,
        token_usage=out.token_usage, cost_usd=out.cost_usd, rationale=rationale)
    _persist(session, workspace_id=workspace_id, item=item, out=deferred,
             model=model, context_hash=context_hash, module_dir=module_dir)
    return deferred


async def run_story_plan_until_done(
    items: list[StoryCodegenItem],
    *,
    session,
    workspace_id: str,
    module_dir: Path,
    context_pack_for: Callable[..., StoryContextPack],
    runner: AgentRunner,
    runner_factory: Callable[[], AgentRunner] | None = None,
    model: str = "sonnet",
    project_index: list[str] | None = None,
    gen_tests: GenTests = generate_story_tests,
    gen_impl: GenImpl = generate_story_implementation,
    run_tests: RunTests = run_targeted_tests,
    now: Clock = time.monotonic,
    repair_max_attempts: int | None = None,
    max_concurrency: int | None = None,
    max_story_attempts: int | None = None,
    build_budget: BuildBudget | None = None,
    on_pass: Callable[[list[StoryCodegenItem]], None] | None = None,
) -> list[StoryRunResult]:
    """REPEAT-UNTIL-DONE wrapper around the single-pass dependency-wave fan-out
    (`run_story_plan`). Per the user's rulings the build must NEVER wedge on one bad
    story and the budget is POOLED with a retained per-story cap (hybrid).

    THE LOOP (always terminates — bounded by attempts AND no-progress AND the pool):

      pass 1 : run the WHOLE plan once (the Task-5 wave fan-out, unchanged).
      pass k : collect the stories still ``failed`` AND still under their attempt cap,
               rebuild ONLY their context (via the caller's ``context_pack_for``), and
               re-run ONLY them. Stop when ANY of:
                 - no story is still ``failed`` (all accepted) -> DONE;
                 - a retry pass yields NO newly-accepted story (NO-PROGRESS);
                 - every still-failing story has reached ``BUILD_MAX_STORY_ATTEMPTS``;
                 - the pooled token budget is exhausted (stop spawning NEW attempts).

    PASS-WITH-DEFERRED: any story still ``failed`` when the loop stops (attempts
    exhausted / no-progress / pool exhausted) is re-stamped TERMINAL ``deferred`` (not
    ``failed``) so a single bad story can never wedge the build. ``deferred`` is NOT in
    the accepted set — the build gate (a later task) decides whether it fails the build.

    POOLED BUDGET (hybrid): ``build_budget`` (default :func:`build_budget_from_env`,
    sized ``story_count * STORY_MAX_TOKENS``) is the build-level pool; its retained
    per-story cap is threaded into every ``run_story`` as a :class:`StoryBudget`, so a
    single story can't exceed its cap AND the loop stops spawning new attempts once the
    pool is drained.

    ``on_pass`` (optional) is called once per pass with the items that pass ran — a test
    hook to assert the pass count is bounded (no infinite loop). Returns the FINAL
    per-story results in the plan's deterministic input order."""
    if max_story_attempts is None:
        max_story_attempts = build_max_story_attempts()
    max_story_attempts = max(1, max_story_attempts)
    if build_budget is None:
        build_budget = build_budget_from_env(len(items))
    per_story_budget = build_budget.story_budget()

    # Per-story attempt counter (how many full passes a story has participated in) and
    # the LATEST result per story. The first pass runs the whole plan.
    attempts: dict[str, int] = {}
    latest: dict[str, StoryRunResult] = {}
    item_by_id = {it.story_id: it for it in items}
    pool_used = 0

    async def _one_pass(pass_items: list[StoryCodegenItem]) -> None:
        nonlocal pool_used
        if on_pass is not None:
            on_pass(pass_items)
        results = await run_story_plan(
            items, session=session, workspace_id=workspace_id, module_dir=module_dir,
            context_pack_for=context_pack_for, runner=runner,
            runner_factory=runner_factory, model=model, project_index=project_index,
            gen_tests=gen_tests, gen_impl=gen_impl, run_tests=run_tests, now=now,
            repair_max_attempts=repair_max_attempts, max_concurrency=max_concurrency,
            budget=per_story_budget, items_override=pass_items)
        for out in results:
            attempts[out.story_id] = attempts.get(out.story_id, 0) + 1
            latest[out.story_id] = out
            pool_used += _pool_tokens(out)

    def _accepted(out: StoryRunResult) -> bool:
        return out.status in _OUTER_ACCEPTED

    def _failed_ids() -> list[str]:
        # Stories still in `failed` (the only retryable status) — in plan order.
        return [it.story_id for it in items
                if latest.get(it.story_id) is not None
                and latest[it.story_id].status == StoryCodegenStatus.failed]

    # --- Pass 1: the whole plan. ------------------------------------------------ #
    await _one_pass(items)

    # --- Repeat-until-done. ----------------------------------------------------- #
    while True:
        failed = _failed_ids()
        if not failed:
            break  # all stories accepted (or terminal non-failed) — DONE.

        # Retry only the failed stories still under their attempt cap.
        retryable = [sid for sid in failed if attempts.get(sid, 0) < max_story_attempts]
        if not retryable:
            break  # every failing story hit BUILD_MAX_STORY_ATTEMPTS — stop, defer.

        # POOLED BUDGET: stop spawning NEW attempts once the pool is drained (no
        # runaway). The still-failing stories are deferred below.
        if build_budget.pool_exhausted(pool_used):
            logger.info("build budget pool exhausted (used=%d) — deferring %d "
                        "still-failing stories", pool_used, len(retryable))
            break

        accepted_before = {sid for sid, out in latest.items() if _accepted(out)}
        retry_items = [item_by_id[sid] for sid in retryable]
        await _one_pass(retry_items)
        accepted_after = {sid for sid, out in latest.items() if _accepted(out)}

        if accepted_after <= accepted_before:
            # NO-PROGRESS: this pass made nothing newly accepted -> stop (defer rest).
            logger.info("repeat-until-done made no progress this pass — stopping")
            break

    # PASS-WITH-DEFERRED: any story still `failed` after the loop stopped is terminal
    # `deferred` (never wedge the build on it).
    for sid in _failed_ids():
        out = latest[sid]
        n = attempts.get(sid, 0)
        reason = (f"still failing after {n} build pass(es) "
                  f"(cap {max_story_attempts}); no-progress/pool/attempt-cap reached")
        item = item_by_id[sid]
        latest[sid] = _mark_deferred(
            session, workspace_id=workspace_id, item=item, out=out, model=model,
            context_hash=_context_hash_for(context_pack_for, item),
            module_dir=module_dir, reason=reason)

    return [latest[it.story_id] for it in items]


def _context_hash_for(context_pack_for: Callable[..., StoryContextPack],
                      item: StoryCodegenItem) -> str:
    """The story's context_hash for the deferred re-stamp — recomputed from the caller's
    pack callback (the same hash the resume policy keys on). Best-effort: if the callback
    raises, fall back to empty (the deferred record still persists; resume simply can't
    short-circuit it, which is the safe direction)."""
    try:
        return _call_context_pack_for(context_pack_for, item, []).context_hash
    except Exception:  # noqa: BLE001 — never let hashing wedge the defer-stamp
        return ""
