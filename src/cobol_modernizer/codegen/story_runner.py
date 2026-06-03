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

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from cobol_modernizer.agent.harness import AgentRunner
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
from cobol_modernizer.codegen.test_runner import StoryTestResult, StoryTestStatus
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


def _test_classes(files: list[GeneratedFile]) -> str:
    """The comma-joined simple test-class names for a `-Dtest=` targeted run, derived
    from the generated test files' paths (Maven accepts a comma list). Empty string
    when there are no test files (the caller then has nothing to target)."""
    names = []
    for f in files:
        if f.kind != "test":
            continue
        stem = Path(f.path).stem
        if stem and stem not in names:
            names.append(stem)
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
# Resume (BASIC — full policy is Task 10)                                     #
# --------------------------------------------------------------------------- #
_ACCEPTED = {StoryCodegenStatus.passed.value,
             StoryCodegenStatus.generated_unverified.value}


def _should_skip(session, *, workspace_id: str, item: StoryCodegenItem,
                 context_hash: str) -> bool:
    """BASIC resume: skip when a prior record for this story exists with an accepted
    status (passed / generated_unverified) AND the SAME context_hash. Anything else
    (failed, different hash, missing) re-runs. Full budget/resume policy is Task 10."""
    prior = get_story_record(session, workspace_id, item.story_id)
    if not prior:
        return False
    return (prior.get("status") in _ACCEPTED
            and prior.get("context_hash") == context_hash)


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
    run_tests: RunTests = None,  # type: ignore[assignment]
    now: Clock = time.monotonic,
    repair_max_attempts: int | None = None,
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
    from cobol_modernizer.codegen.test_runner import run_targeted_tests
    if run_tests is None:
        run_tests = run_targeted_tests
    if repair_max_attempts is None:
        repair_max_attempts = story_repair_max_attempts()
    project_index = project_index or []
    context_hash = context_pack.context_hash

    # 1. BASIC resume — skip an already-accepted story whose context is unchanged.
    if _should_skip(session, workspace_id=workspace_id, item=item,
                    context_hash=context_hash):
        logger.info("story %s: skipped (accepted + unchanged context_hash)",
                    item.story_id)
        return StoryRunResult(story_id=item.story_id,
                              status=StoryCodegenStatus.skipped, skipped=True)

    started = now()
    usage_before = _usage_snapshot(runner)
    cost_before = float(getattr(runner, "cost_usd", 0.0) or 0.0)

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
    logger.info("story %s: red baseline status=%s", item.story_id, red.status.value)

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
    #    from the failing log excerpt + the touched files (mirrors run_repair_loop's
    #    feedback shape), re-write, re-run. toolchain_unavailable is NOT repairable
    #    (re-running mvn will not help) so we break out.
    while (result.status != StoryTestStatus.ok
           and result.status != StoryTestStatus.toolchain_unavailable
           and attempts < repair_max_attempts + 1):
        logger.info("story %s: repair attempt %d (gate=%s)",
                    item.story_id, attempts, result.status.value)
        impl_patch = await gen_impl(
            runner=runner, item=item, context_pack=context_pack,
            failing_tests=test_files, existing_java=_existing_java(module_dir),
            model=model,
            repair_feedback={"failing_gate": result.status.value,
                             "log_excerpt": result.log_excerpt,
                             "touched_files": changed})
        impl_files = list(impl_patch.files)
        changed = _write_files(module_dir, impl_files)
        attempts += 1
        result = run_tests(module_dir, target)

    # 6. GATE — decide the recorded status from AC coverage + lineage + test result.
    ac_covered = scan_generated_test_refs(module_dir, item.acceptance_criteria_ids)
    ac_missing = sorted(set(item.acceptance_criteria_ids) - set(ac_covered))
    ac_ok = not ac_missing
    lineage_ok = _cites_lineage(impl_files, story_id=item.story_id,
                                cobol_refs=item.cobol_refs)

    status = _decide_status(result=result, ac_ok=ac_ok, lineage_ok=lineage_ok)

    wall = now() - started
    out = StoryRunResult(
        story_id=item.story_id, status=status, test_result=result,
        red_status=red.status, attempts=attempts,
        ac_covered=ac_covered, ac_missing=ac_missing, changed_files=changed,
        wall_time_s=wall,
        token_usage=_usage_delta(usage_before, _usage_snapshot(runner)),
        cost_usd=float(getattr(runner, "cost_usd", 0.0) or 0.0) - cost_before,
        rationale="; ".join(r for r in (tests_patch.rationale, impl_patch.rationale)
                            if r))
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
    outcomes. Only when both hold does the test result decide passed (GREEN) vs
    generated_unverified (toolchain absent) vs failed (still red)."""
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
async def run_story_plan(
    items: list[StoryCodegenItem],
    *,
    session,
    workspace_id: str,
    module_dir: Path,
    context_pack_for: Callable[[StoryCodegenItem], StoryContextPack],
    runner: AgentRunner,
    model: str = "sonnet",
    project_index: list[str] | None = None,
    gen_tests: GenTests = generate_story_tests,
    gen_impl: GenImpl = generate_story_implementation,
    run_tests: RunTests = None,  # type: ignore[assignment]
    now: Clock = time.monotonic,
    repair_max_attempts: int | None = None,
) -> list[StoryRunResult]:
    """Run a plan's stories IN ORDER (the plan is already dependency-sorted by
    `build_story_codegen_plan`). The caller supplies `context_pack_for` to resolve
    each item's already-built pack (it owns the slice-pack/scaffold; the runner does
    not). Each `run_story` records that story's `generated_test_refs` against the
    shared module dir, so by the end the Verify gate sees every cited AC."""
    results: list[StoryRunResult] = []
    for item in items:
        pack = context_pack_for(item)
        results.append(await run_story(
            item, session=session, workspace_id=workspace_id,
            module_dir=module_dir, context_pack=pack, runner=runner, model=model,
            project_index=project_index, gen_tests=gen_tests, gen_impl=gen_impl,
            run_tests=run_tests, now=now, repair_max_attempts=repair_max_attempts))
    return results
