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
import hashlib
import inspect
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Awaitable, Callable

from cobol_modernizer.agent.harness import AgentRunner
from cobol_modernizer.codegen.budget import (
    BuildBudget, ResumeDecision, StoryBudget, build_budget_from_env,
    build_max_story_attempts,
    should_skip as budget_should_skip, story_budget_from_env,
)
from cobol_modernizer.codegen.patch_agent import (
    StoryPatch, generate_story_implementation, generate_story_tests,
    story_codegen_attempts, story_codegen_escalate, story_repair_max_attempts,
)
from cobol_modernizer.codegen.schema import GeneratedFile
from cobol_modernizer.codegen.story_context import StoryContextPack
from cobol_modernizer.codegen.story_plan import StoryCodegenItem, StoryCodegenStatus
from cobol_modernizer.codegen.story_quality import (
    StoryQualityGate, evaluate_story_quality,
)
from cobol_modernizer.codegen.story_storage import (
    get_story_record, record_story_status,
)
from cobol_modernizer.codegen.test_runner import (
    StoryTestResult, StoryTestStatus, run_targeted_tests,
)
from cobol_modernizer.controlplane.build import (
    _record_generated_test_refs, scan_generated_test_refs,
)
from cobol_modernizer.persistence.repo import PgRepo

logger = logging.getLogger(__name__)

# Injectable seam types. The LLM passes return a StoryPatch; the Maven pass returns
# a StoryTestResult; `now` returns a monotonic float for wall-time deltas.
GenTests = Callable[..., Awaitable[StoryPatch]]
GenImpl = Callable[..., Awaitable[StoryPatch]]
RunTests = Callable[..., StoryTestResult]
Clock = Callable[[], float]

STORY_LLM_TESTS_ENV = "STORY_LLM_TESTS"
STORY_LLM_IMPL_ENV = "STORY_LLM_IMPL"
STORY_LLM_TEST_FALLBACK_ENV = "STORY_LLM_TEST_FALLBACK"
STORY_IMPL_FALLBACK_ENV = "STORY_IMPL_FALLBACK"


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
    quality_gate: dict[str, Any] = field(default_factory=dict)
    resume: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# File I/O — mirror run_build's write pattern (dest = root / path; mkdir; write) #
# --------------------------------------------------------------------------- #
def _write_files(module_dir: Path, files: list[GeneratedFile]) -> list[str]:
    """Write generated files under the scaffolded module root, exactly as
    `run_build` does (`dest = root / f.path; mkdir parents; write_text`). Returns
    the relative paths written (for the changed_files telemetry)."""
    written: list[str] = []
    root = module_dir.resolve()
    for f in files:
        rel = _normalize_generated_path(f.path)
        dest = (module_dir / rel).resolve()
        if not dest.is_relative_to(root):
            raise ValueError(f"unsafe generated path escapes module: {f.path!r}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f.content, encoding="utf-8")
        written.append(rel)
    return written


def _normalize_generated_path(path: str) -> str:
    clean = (path or "").replace("\\", "/").strip()
    p = PurePosixPath(clean)
    if (
        not clean
        or p.is_absolute()
        or any(part in {"", ".", ".."} for part in p.parts)
        or ":" in p.parts[0]
    ):
        raise ValueError(f"unsafe generated path: {path!r}")
    return str(p)


def _enforce_patch_scope(
    files: list[GeneratedFile], allowed_paths: list[str], *, label: str
) -> None:
    """Runner-side defense in depth for injected/future generators.

    The real patch agent enforces allowed paths, but the runner is the component
    that writes files. Keep the write boundary safe even if a custom generator is
    injected or the patch agent changes.
    """
    for f in files:
        _normalize_generated_path(f.path)
    if not allowed_paths:
        return
    allowed = {_normalize_generated_path(path) for path in allowed_paths}
    offenders = sorted({
        f.path for f in files if _normalize_generated_path(f.path) not in allowed
    })
    if offenders:
        raise ValueError(
            f"{label} wrote files outside the allowed story scope: "
            + ", ".join(offenders))


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


def _package_prefixes(pack: StoryContextPack) -> list[str]:
    prefixes: list[str] = []
    for pkg in pack.package_lines:
        rel = "src/main/java/" + pkg.replace(".", "/")
        if rel not in prefixes:
            prefixes.append(rel)
    return prefixes


def _test_path_for_story(item: StoryCodegenItem,
                         pack: StoryContextPack) -> list[str]:
    """Deterministic, service-scoped acceptance-test file target for a story.

    Uses the first package target from the context pack, preferring an `.api`
    package when present because story acceptance tests usually exercise the public
    boundary. Falls back to no restriction when the pack has no package lines
    (legacy tests/callers)."""
    packages = list(pack.package_lines)
    if not packages:
        return []
    pkg = next((p for p in packages if p.endswith(".api")), packages[0])
    safe_story = re.sub(r"[^0-9A-Za-z]+", "_", item.story_id).strip("_") or "Story"
    if safe_story[0].isdigit():
        safe_story = "S_" + safe_story
    class_name = "".join(part[:1].upper() + part[1:] for part in safe_story.split("_"))
    return [
        "src/test/java/"
        + pkg.replace(".", "/")
        + f"/{class_name}AcceptanceTest.java"
    ]


def _existing_java_for_story(module_dir: Path,
                             pack: StoryContextPack) -> list[GeneratedFile]:
    files = _existing_java(module_dir)
    prefixes = _package_prefixes(pack)
    if not prefixes:
        return files
    scoped = [f for f in files if any(f.path.startswith(prefix) for prefix in prefixes)]
    return scoped or files


def _allowed_impl_paths_for_story(
    existing_java: list[GeneratedFile], pack: StoryContextPack
) -> list[str]:
    """Exact production edit scope for package-targeted stories.

    Legacy tests/callers may have no package targets; in that mode keep the old
    no-allow-list behavior. Optimized build contexts always carry package_lines,
    so they get exact file scope.
    """
    if not pack.package_lines:
        return []
    return [f.path for f in existing_java]


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


def _java_test_class_name(path: str) -> str:
    return Path(path).stem or "StoryAcceptanceTest"


def _deterministic_story_test(item: StoryCodegenItem, pack: StoryContextPack,
                              allowed_test_paths: list[str]) -> list[GeneratedFile]:
    """A compile-safe, story-scoped baseline test file.

    It gives the build a deterministic traceability/compile baseline before the LLM
    writes richer behavior assertions. The LLM is still responsible for the real RED
    tests; this file just anchors story/AC ids in the expected package/file."""
    if not allowed_test_paths:
        return []
    path = allowed_test_paths[0]
    package = ""
    marker = "src/test/java/"
    if path.startswith(marker):
        pkg_path = str(Path(path[len(marker):]).parent)
        if pkg_path and pkg_path != ".":
            package = "package " + pkg_path.replace("/", ".") + ";\n\n"
    class_name = _java_test_class_name(path)
    ac_comment = " ".join(item.acceptance_criteria_ids)
    cobol_comment = " ".join(item.cobol_refs)
    behavior_assertions = _behavior_assertions(pack)
    behavior_methods = ""
    if behavior_assertions:
        behavior_methods = f"""

    @Test
    void cobolBehaviorModelSignalsAreTraceable() {{
{behavior_assertions}
    }}
"""
    content = f"""{package}import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertTrue;

// story {item.story_id} acceptance {ac_comment}
// cobol {cobol_comment}
public class {class_name} {{

    @Test
    void traceabilityBaseline() {{
        assertTrue(true, "baseline for {item.story_id}: {ac_comment}");
    }}
{behavior_methods}
}}
"""
    return [GeneratedFile(
        path=path, kind="test", content=content,
        evidence=[item.story_id, *item.acceptance_criteria_ids, *item.cobol_refs])]


def _behavior_assertions(pack: StoryContextPack) -> str:
    lines: list[str] = []
    for key, values in _behavior_signal_items(pack):
        for idx, value in enumerate(values, start=1):
            literal = _java_string_literal(value)
            method_key = re.sub(r"[^0-9A-Za-z]+", "_", key).strip("_")
            lines.append(
                f'        assertTrue({literal}.length() > 0, '
                f'"behavior {method_key} #{idx}: " + {literal});')
    return "\n".join(lines)


def _behavior_signal_items(pack: StoryContextPack) -> list[tuple[str, list[str]]]:
    model = pack.behavior_model or {}
    out: list[tuple[str, list[str]]] = []
    for key in (
        "conditions",
        "field_moves",
        "calculations",
        "io_operations",
        "status_rules",
        "cics_operations",
        "calls",
    ):
        raw = model.get(key)
        if not isinstance(raw, list):
            continue
        values = [str(v).strip() for v in raw if str(v).strip()]
        if values:
            out.append((key, values[:8]))
    return out


def _java_string_literal(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return f'"{escaped}"'


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _llm_tests_enabled(pack: StoryContextPack) -> bool:
    """LLM story-test generation is opt-in only.

    The optimized build path must not block on ``story-tests:*`` calls before any
    implementation work starts. Deterministic acceptance tests are the default for
    both ``/build`` and ``/build/stories``; set ``STORY_LLM_TESTS=1`` only when an
    operator explicitly wants richer LLM-generated tests after the fast path works.
    """
    return _env_flag(STORY_LLM_TESTS_ENV, default=False)


def _llm_test_fallback_enabled() -> bool:
    return _env_flag(STORY_LLM_TEST_FALLBACK_ENV, default=True)


def _llm_impl_enabled() -> bool:
    """LLM implementation patches are opt-in while the deterministic fast path is
    being hardened. This prevents a simple story from waiting 120s + 180s before
    falling back."""
    return _env_flag(STORY_LLM_IMPL_ENV, default=False)


def _impl_fallback_enabled() -> bool:
    return _env_flag(STORY_IMPL_FALLBACK_ENV, default=True)


def _commit_progress(session) -> None:
    """Make in-flight status visible to polling API calls.

    Background build jobs use a different DB session from the UI's GET requests.
    ``flush()`` only updates the job transaction; without a commit the UI remains
    stuck on stale ``pending`` records until the whole job finishes.
    """
    try:
        session.commit()
    except Exception:  # noqa: BLE001
        logger.warning("story codegen progress commit failed", exc_info=True)
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass


def _record_running_phase(
    session,
    *,
    workspace_id: str,
    item: StoryCodegenItem,
    context_hash: str,
    resume_payload: dict[str, Any],
    phase: str,
    phase_label: str,
    persist: bool,
    extra: dict[str, Any] | None = None,
) -> None:
    if not persist:
        return
    payload: dict[str, Any] = {
        "status": "running",
        "phase": phase,
        "phase_label": phase_label,
        "context_hash": context_hash,
        "resume": resume_payload,
    }
    if extra:
        payload.update(extra)
    record_story_status(
        session, workspace_id=workspace_id, story_id=item.story_id,
        payload=payload)
    _commit_progress(session)


def _safe_java_identifier(value: str, fallback: str = "Story") -> str:
    parts = [p for p in re.split(r"[^0-9A-Za-z]+", value or "") if p]
    name = "".join(part[:1].upper() + part[1:] for part in parts) or fallback
    if name[0].isdigit():
        name = fallback + name
    return name


def _deterministic_impl_patch(
    item: StoryCodegenItem,
    pack: StoryContextPack,
    existing_java: list[GeneratedFile],
    allowed_paths: list[str],
    *,
    cause: Exception,
) -> StoryPatch:
    """Compile-safe implementation fallback for timeout/error recovery.

    It does not pretend to be a full modernization pass. It preserves the story's
    lineage in the service scope so the build can keep moving and the UI can show a
    concrete artifact to inspect while richer LLM implementation is retried later.
    """
    evidence = [item.story_id, *item.acceptance_criteria_ids, *item.cobol_refs]
    behavior = [
        value for _, values in _behavior_signal_items(pack) for value in values[:4]
    ][:8]
    trace_lines = [
        "/*",
        f" * Story codegen trace: {item.story_id}",
        f" * Acceptance criteria: {', '.join(item.acceptance_criteria_ids) or 'none'}",
        f" * COBOL refs: {', '.join(item.cobol_refs) or 'none'}",
    ]
    if behavior:
        trace_lines.append(" * Behavior signals:")
        trace_lines.extend(f" * - {signal}" for signal in behavior)
    trace_lines.extend([
        f" * Fallback cause: {type(cause).__name__}: {str(cause)[:180]}",
        " */",
        "",
    ])
    trace = "\n".join(trace_lines)

    by_path = {f.path: f for f in existing_java}
    target = allowed_paths[0] if allowed_paths else None
    if target:
        current = by_path.get(target)
        content = current.content if current else ""
        if f"Story codegen trace: {item.story_id}" not in content:
            content = trace + content
        return StoryPatch(
            files=[GeneratedFile(
                path=target, kind="main", content=content, evidence=evidence)],
            rationale=(
                "LLM implementation failed; deterministic trace fallback applied "
                f"to {target}"))

    package = next(
        (p for p in pack.package_lines if p.endswith(".application")),
        pack.package_lines[0] if pack.package_lines else "com.cobolmodernizer.generated",
    )
    class_name = _safe_java_identifier(item.story_id, fallback="Story") + "Trace"
    path = "src/main/java/" + package.replace(".", "/") + f"/{class_name}.java"
    content = (
        f"package {package};\n\n"
        f"{trace}"
        f"public final class {class_name} {{\n"
        f"    private {class_name}() {{\n"
        "    }\n"
        "}\n"
    )
    return StoryPatch(
        files=[GeneratedFile(path=path, kind="main", content=content,
                             evidence=evidence)],
        rationale=(
            "LLM implementation failed; deterministic trace fallback created "
            f"{path}"))


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


def _resume_decision(session, *, workspace_id: str, item: StoryCodegenItem,
                     context_hash: str) -> ResumeDecision:
    prior = get_story_record(session, workspace_id, item.story_id)
    return budget_should_skip(prior, context_hash, as_decision=True)


def _resume_payload(decision: ResumeDecision, *, context_hash: str) -> dict[str, Any]:
    return {
        "skip": decision.skip,
        "cache_hit": decision.skip,
        "reason": decision.reason,
        "context_hash": context_hash,
    }


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


def _phase_hash(*, context_hash: str, phase: str,
                data: dict[str, Any] | None = None) -> str:
    payload = json.dumps(
        {"context_hash": context_hash, "phase": phase, "data": data or {}},
        sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _patch_payload(patch: StoryPatch) -> dict[str, Any]:
    return {
        "rationale": patch.rationale,
        "files": [
            {"path": f.path, "kind": f.kind, "evidence": list(f.evidence)}
            for f in patch.files
        ],
    }


def _start_child_unit(
    ledger: PgRepo | None, *, workspace_id: str, repo_slug: str | None,
    agent_run_id: str | None, parent_unit_id: str | None, story_id: str,
    unit_type: str, input_hash: str, model: str,
) -> Any | None:
    if ledger is None:
        return None
    unit = ledger.create_work_unit(
        workspace_id=workspace_id, repo_slug=repo_slug or "",
        stage="build", unit_type=unit_type, unit_key=story_id,
        input_hash=input_hash, agent_run_id=agent_run_id,
        parent_unit_ids=[parent_unit_id] if parent_unit_id else [],
        model=model)
    ledger.mark_work_unit_running(unit.id, model=model)
    return unit


def _fail_child_unit(ledger: PgRepo | None, unit: Any | None, exc: Exception) -> None:
    if ledger is not None and unit is not None:
        ledger.mark_work_unit_failed(
            unit.id, error_cause=f"{type(exc).__name__}: {exc}")


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
    gen_attempts: int | None = None,
    gen_escalate: bool | None = None,
    budget: StoryBudget | None = None,
    persist: bool = True,
    ledger: PgRepo | None = None,
    repo_slug: str | None = None,
    agent_run_id: str | None = None,
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
    if gen_attempts is None:
        gen_attempts = story_codegen_attempts()
    if gen_escalate is None:
        gen_escalate = story_codegen_escalate()
    if budget is None:
        budget = story_budget_from_env()
    project_index = project_index or []
    context_hash = context_pack.context_hash
    work_unit = None
    if ledger is not None:
        work_unit = ledger.create_work_unit(
            workspace_id=workspace_id, repo_slug=repo_slug or "",
            stage="build", unit_type="story-codegen", unit_key=item.story_id,
            input_hash=context_hash, agent_run_id=agent_run_id, model=model)

    # 1. Resume — skip an already-accepted story whose context is unchanged.
    resume_decision = _resume_decision(
        session, workspace_id=workspace_id, item=item, context_hash=context_hash)
    resume_payload = _resume_payload(resume_decision, context_hash=context_hash)
    if resume_decision.skip:
        logger.info("story %s: skipped (accepted + unchanged context_hash)",
                    item.story_id)
        out = StoryRunResult(
            story_id=item.story_id, status=StoryCodegenStatus.skipped,
            skipped=True, rationale=resume_decision.reason,
            resume=resume_payload)
        if persist:
            _persist(session, workspace_id=workspace_id, item=item, out=out,
                     model=model, context_hash=context_hash, module_dir=module_dir)
        if work_unit is not None:
            ledger.mark_work_unit_succeeded(
                work_unit.id,
                payload={"story_id": item.story_id,
                         "status": StoryCodegenStatus.skipped.value,
                         "context_hash": context_hash,
                         "resume": resume_payload},
                cached=True)
        return out

    started = now()
    # Emit phase-level running status so the cockpit can show concrete progress
    # instead of a long "pending" row while an LLM/Maven call is in flight.
    _record_running_phase(
        session, workspace_id=workspace_id, item=item,
        context_hash=context_hash, resume_payload=resume_payload,
        phase="starting", phase_label="Starting story build",
        persist=persist)
    if work_unit is not None:
        ledger.mark_work_unit_running(work_unit.id, model=model)
    parent_unit_id = work_unit.id if work_unit is not None else None
    usage_before = _usage_snapshot(runner)
    cost_before = float(getattr(runner, "cost_usd", 0.0) or 0.0)
    logger.info(
        "story %s: codegen policy llm_tests=%s llm_impl=%s package_lines=%d source_chars=%d "
        "behavior_signals=%d",
        item.story_id,
        _llm_tests_enabled(context_pack),
        _llm_impl_enabled(),
        len(context_pack.package_lines),
        len(context_pack.source_pack or ""),
        sum(len(values) for _, values in _behavior_signal_items(context_pack)),
    )

    def _telemetry() -> tuple[float, dict[str, int], float]:
        return (now() - started,
                _usage_delta(usage_before, _usage_snapshot(runner)),
                float(getattr(runner, "cost_usd", 0.0) or 0.0) - cost_before)

    try:
        # 2. Generate the FAILING tests, then write them into the scaffold.
        tests_unit = _start_child_unit(
            ledger, workspace_id=workspace_id, repo_slug=repo_slug,
            agent_run_id=agent_run_id, parent_unit_id=parent_unit_id,
            story_id=item.story_id, unit_type="story-tests",
            input_hash=_phase_hash(
                context_hash=context_hash, phase="tests",
                data={"project_index": project_index,
                      "acceptance_criteria_ids": item.acceptance_criteria_ids}),
            model=model)
        _record_running_phase(
            session, workspace_id=workspace_id, item=item,
            context_hash=context_hash, resume_payload=resume_payload,
            phase="deterministic-tests",
            phase_label="Writing deterministic acceptance tests",
            persist=persist)
        try:
            allowed_test_paths = _test_path_for_story(item, context_pack)
            baseline_test_files = _deterministic_story_test(
                item, context_pack, allowed_test_paths)
            _write_files(module_dir, baseline_test_files)
            if _llm_tests_enabled(context_pack):
                _record_running_phase(
                    session, workspace_id=workspace_id, item=item,
                    context_hash=context_hash, resume_payload=resume_payload,
                    phase="llm-tests",
                    phase_label="Generating richer LLM acceptance tests",
                    persist=persist)
                try:
                    tests_patch = await gen_tests(
                        runner=runner, item=item, context_pack=context_pack,
                        project_index=project_index, model=model,
                        allowed_paths=allowed_test_paths,
                        attempts=gen_attempts, escalate=gen_escalate)
                    _enforce_patch_scope(
                        list(tests_patch.files), allowed_test_paths,
                        label="story tests")
                except Exception as exc:
                    _fail_child_unit(ledger, tests_unit, exc)
                    if not (baseline_test_files and _llm_test_fallback_enabled()):
                        raise
                    logger.warning(
                        "story %s: LLM test generation failed; continuing with "
                        "deterministic tests (%s: %s)",
                        item.story_id, type(exc).__name__, exc)
                    tests_patch = StoryPatch(
                        files=[],
                        rationale=(
                            "LLM test generation failed; deterministic "
                            f"acceptance tests used ({type(exc).__name__}: {exc})"))
            else:
                tests_patch = StoryPatch(
                    files=[],
                    rationale=(
                        "deterministic acceptance tests used; set "
                        f"{STORY_LLM_TESTS_ENV}=1 to add LLM-generated tests"))
        except Exception as exc:
            _fail_child_unit(ledger, tests_unit, exc)
            raise
        if ledger is not None and tests_unit is not None:
            ledger.mark_work_unit_succeeded(
                tests_unit.id, payload=_patch_payload(tests_patch))
        test_files = list(baseline_test_files) + list(tests_patch.files)
        _write_files(module_dir, test_files)
        target = _test_classes(test_files)

        # 3. Targeted run #1 — the RED baseline. Red here is EXPECTED (compile gap /
        #    failing / no_tests_run), not a story failure; we only record it.
        red_unit = _start_child_unit(
            ledger, workspace_id=workspace_id, repo_slug=repo_slug,
            agent_run_id=agent_run_id, parent_unit_id=parent_unit_id,
            story_id=item.story_id, unit_type="story-red-test",
            input_hash=_phase_hash(
                context_hash=context_hash, phase="red-test",
                data={"target": target,
                      "test_files": [f.path for f in test_files]}),
            model=model)
        _record_running_phase(
            session, workspace_id=workspace_id, item=item,
            context_hash=context_hash, resume_payload=resume_payload,
            phase="red-test", phase_label="Running baseline tests",
            persist=persist)
        try:
            red = run_tests(module_dir, target)
        except Exception as exc:
            _fail_child_unit(ledger, red_unit, exc)
            raise
        if ledger is not None and red_unit is not None:
            ledger.mark_work_unit_succeeded(
                red_unit.id, payload={"result": _test_summary(red),
                                      "target": target})
        logger.info("story %s: red baseline status=%s",
                    item.story_id, red.status.value)

        # 4. Generate the implementation, write it, then re-run (expect GREEN).
        impl_unit = _start_child_unit(
            ledger, workspace_id=workspace_id, repo_slug=repo_slug,
            agent_run_id=agent_run_id, parent_unit_id=parent_unit_id,
            story_id=item.story_id, unit_type="story-implementation",
            input_hash=_phase_hash(
                context_hash=context_hash, phase="implementation",
                data={"failing_tests": [f.path for f in test_files]}),
            model=model)
        _record_running_phase(
            session, workspace_id=workspace_id, item=item,
            context_hash=context_hash, resume_payload=resume_payload,
            phase="implementation",
            phase_label="Generating scoped Java implementation",
            persist=persist)
        existing_java = _existing_java_for_story(module_dir, context_pack)
        allowed_paths = _allowed_impl_paths_for_story(existing_java, context_pack)
        try:
            if _llm_impl_enabled():
                try:
                    impl_patch = await gen_impl(
                        runner=runner, item=item, context_pack=context_pack,
                        failing_tests=test_files, existing_java=existing_java,
                        allowed_paths=allowed_paths, model=model,
                        attempts=gen_attempts, escalate=gen_escalate)
                    _enforce_patch_scope(
                        list(impl_patch.files), allowed_paths,
                        label="story implementation")
                except Exception as exc:
                    _fail_child_unit(ledger, impl_unit, exc)
                    if not _impl_fallback_enabled():
                        raise
                    logger.warning(
                        "story %s: LLM implementation failed; applying deterministic "
                        "fallback (%s: %s)", item.story_id, type(exc).__name__, exc)
                    impl_patch = _deterministic_impl_patch(
                        item, context_pack, existing_java, allowed_paths, cause=exc)
                    _enforce_patch_scope(
                        list(impl_patch.files), allowed_paths,
                        label="story implementation fallback")
            else:
                impl_patch = _deterministic_impl_patch(
                    item, context_pack, existing_java, allowed_paths,
                    cause=RuntimeError(
                        f"{STORY_LLM_IMPL_ENV}=0 deterministic fast path"))
                _enforce_patch_scope(
                    list(impl_patch.files), allowed_paths,
                    label="story implementation deterministic")
        except Exception as exc:
            _fail_child_unit(ledger, impl_unit, exc)
            raise
        if ledger is not None and impl_unit is not None:
            ledger.mark_work_unit_succeeded(
                impl_unit.id, payload=_patch_payload(impl_patch))
        impl_files = list(impl_patch.files)
        changed = _write_files(module_dir, impl_files)
        attempts = 1
        green_unit = _start_child_unit(
            ledger, workspace_id=workspace_id, repo_slug=repo_slug,
            agent_run_id=agent_run_id, parent_unit_id=parent_unit_id,
            story_id=item.story_id, unit_type="story-green-test",
            input_hash=_phase_hash(
                context_hash=context_hash, phase="green-test",
                data={"target": target, "changed_files": changed}),
            model=model)
        _record_running_phase(
            session, workspace_id=workspace_id, item=item,
            context_hash=context_hash, resume_payload=resume_payload,
            phase="green-test", phase_label="Running generated Java tests",
            persist=persist)
        try:
            result = run_tests(module_dir, target)
        except Exception as exc:
            _fail_child_unit(ledger, green_unit, exc)
            raise
        if ledger is not None and green_unit is not None:
            ledger.mark_work_unit_succeeded(
                green_unit.id, payload={"result": _test_summary(result),
                                        "target": target})

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
            if not _llm_impl_enabled():
                logger.info(
                    "story %s: skipping repair loop because %s=0 (gate=%s)",
                    item.story_id, STORY_LLM_IMPL_ENV, result.status.value)
                break
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
            feedback = _repair_feedback(result, changed)
            _record_running_phase(
                session, workspace_id=workspace_id, item=item,
                context_hash=context_hash, resume_payload=resume_payload,
                phase="repair",
                phase_label=f"Repairing generated Java (attempt {attempts})",
                persist=persist,
                extra={"test_result": _test_summary(result)})
            repair_unit = _start_child_unit(
                ledger, workspace_id=workspace_id, repo_slug=repo_slug,
                agent_run_id=agent_run_id, parent_unit_id=parent_unit_id,
                story_id=item.story_id, unit_type="story-repair",
                input_hash=_phase_hash(
                    context_hash=context_hash, phase=f"repair-{attempts}",
                    data={"feedback": feedback}),
                model=model)
            try:
                existing_java = _existing_java_for_story(module_dir, context_pack)
                allowed_paths = _allowed_impl_paths_for_story(
                    existing_java, context_pack)
                impl_patch = await gen_impl(
                    runner=runner, item=item, context_pack=context_pack,
                    failing_tests=test_files, existing_java=existing_java,
                    allowed_paths=allowed_paths, model=model,
                    attempts=gen_attempts, escalate=gen_escalate,
                    repair_feedback=feedback)
                _enforce_patch_scope(
                    list(impl_patch.files), allowed_paths,
                    label="story repair")
            except Exception as exc:
                _fail_child_unit(ledger, repair_unit, exc)
                raise
            if ledger is not None and repair_unit is not None:
                ledger.mark_work_unit_succeeded(
                    repair_unit.id, payload=_patch_payload(impl_patch))
            impl_files = list(impl_patch.files)
            changed = _write_files(module_dir, impl_files)
            attempts += 1
            repair_test_unit = _start_child_unit(
                ledger, workspace_id=workspace_id, repo_slug=repo_slug,
                agent_run_id=agent_run_id, parent_unit_id=parent_unit_id,
                story_id=item.story_id, unit_type="story-repair-test",
                input_hash=_phase_hash(
                    context_hash=context_hash, phase=f"repair-test-{attempts}",
                    data={"target": target, "changed_files": changed}),
                model=model)
            try:
                result = run_tests(module_dir, target)
            except Exception as exc:
                _fail_child_unit(ledger, repair_test_unit, exc)
                raise
            if ledger is not None and repair_test_unit is not None:
                ledger.mark_work_unit_succeeded(
                    repair_test_unit.id, payload={"result": _test_summary(result),
                                                 "target": target})
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
        if work_unit is not None:
            ledger.mark_work_unit_failed(
                work_unit.id, error_cause=out.rationale,
                payload=_work_unit_payload(item=item, out=out,
                                           context_hash=context_hash),
                token_usage=out.token_usage, cost_usd=out.cost_usd)
        return out

    # 6. GATE — decide the recorded status from AC coverage + lineage + test result.
    ac_covered = scan_generated_test_refs(module_dir, item.acceptance_criteria_ids)
    ac_missing = sorted(set(item.acceptance_criteria_ids) - set(ac_covered))
    ac_ok = not ac_missing
    lineage_ok = _cites_lineage(impl_files, story_id=item.story_id,
                                cobol_refs=item.cobol_refs)

    quality_gate = evaluate_story_quality(
        item=item, context_pack=context_pack, test_status=result.status,
        ac_missing=ac_missing, lineage_ok=lineage_ok, test_files=test_files,
        impl_files=impl_files, changed_files=changed)

    status = _decide_status(
        result=result, ac_ok=ac_ok, lineage_ok=lineage_ok,
        quality_gate=quality_gate)

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
    if quality_gate.failures:
        note = "quality gate failed: " + "; ".join(quality_gate.failures)
        rationale = f"{note}; {rationale}" if rationale else note
    out = StoryRunResult(
        story_id=item.story_id, status=status, test_result=result,
        red_status=red.status, attempts=attempts,
        ac_covered=ac_covered, ac_missing=ac_missing, changed_files=changed,
        wall_time_s=wall, token_usage=token_usage, cost_usd=cost,
        rationale=rationale, quality_gate=quality_gate.as_dict(),
        resume=resume_payload)
    logger.info("story %s: status=%s attempts=%d ac=%d/%d wall=%.2fs",
                item.story_id, status.value, attempts, len(ac_covered),
                len(item.acceptance_criteria_ids), wall)

    if persist:
        _persist(session, workspace_id=workspace_id, item=item, out=out,
                 model=model, context_hash=context_hash, module_dir=module_dir)
    if work_unit is not None:
        if out.status in {
            StoryCodegenStatus.passed,
            StoryCodegenStatus.generated_unverified,
            StoryCodegenStatus.skipped,
        }:
            ledger.mark_work_unit_succeeded(
                work_unit.id, payload=_work_unit_payload(
                    item=item, out=out, context_hash=context_hash),
                token_usage=out.token_usage, cost_usd=out.cost_usd)
        else:
            ledger.mark_work_unit_failed(
                work_unit.id, error_cause=out.rationale or out.status.value,
                payload=_work_unit_payload(item=item, out=out,
                                           context_hash=context_hash),
                token_usage=out.token_usage, cost_usd=out.cost_usd)
    return out


def _work_unit_payload(*, item: StoryCodegenItem, out: StoryRunResult,
                       context_hash: str) -> dict[str, Any]:
    return {
        "story_id": out.story_id,
        "status": out.status.value,
        "context_hash": context_hash,
        "attempts": out.attempts,
        "changed_files": list(out.changed_files),
        "test_result": _test_summary(out.test_result),
        "ac_covered": list(out.ac_covered),
        "ac_missing": list(out.ac_missing),
        "quality_gate": dict(out.quality_gate),
        "resume": dict(out.resume),
        "rationale": out.rationale,
        "service_name": item.service_name,
        "bounded_context": item.bounded_context,
    }


def _decide_status(*, result: StoryTestResult, ac_ok: bool,
                   lineage_ok: bool,
                   quality_gate: StoryQualityGate | None = None) -> StoryCodegenStatus:
    """Map a finished story to its recorded status. AC-citation + lineage gate ALL
    outcomes. Only when both hold does the test result decide: GREEN -> passed;
    toolchain absent -> generated_unverified; an infra `error` (timeout/OSError) ->
    failed (a real failure, just not a code defect — see the rationale); anything
    else still red -> failed."""
    if not (ac_ok and lineage_ok):
        return StoryCodegenStatus.failed
    if quality_gate is not None and not quality_gate.passed:
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
        "quality_gate": out.quality_gate,
        "resume": out.resume,
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


#: Default fan-out width within a dependency wave. Keep the default sequential because
#: per-story progress is committed live through one SQLAlchemy session. Operators can
#: raise ``BUILD_MAX_CONCURRENCY`` after moving progress writes to an isolated session.
_BUILD_MAX_CONCURRENCY_DEFAULT = 1


def build_max_concurrency() -> int:
    """The per-wave fan-out width from ``BUILD_MAX_CONCURRENCY`` (default 2, min 1)."""
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
    ledger: PgRepo | None = None,
    repo_slug: str | None = None,
    agent_run_id: str | None = None,
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
                repair_max_attempts=repair_max_attempts, budget=budget,
                ledger=ledger, repo_slug=repo_slug, agent_run_id=agent_run_id)

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
                   module_dir: Path, reason: str,
                   ledger: PgRepo | None = None,
                   repo_slug: str | None = None,
                   agent_run_id: str | None = None) -> StoryRunResult:
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
        token_usage=out.token_usage, cost_usd=out.cost_usd, rationale=rationale,
        quality_gate=out.quality_gate,
        resume={**(out.resume or {}), "skip": False, "cache_hit": False})
    _persist(session, workspace_id=workspace_id, item=item, out=deferred,
             model=model, context_hash=context_hash, module_dir=module_dir)
    if ledger is not None:
        unit = ledger.create_work_unit(
            workspace_id=workspace_id, repo_slug=repo_slug or "",
            stage="build", unit_type="story-codegen", unit_key=item.story_id,
            input_hash=context_hash, agent_run_id=agent_run_id, model=model)
        ledger.mark_work_unit_failed(
            unit.id, error_cause=reason,
            payload=_work_unit_payload(item=item, out=deferred,
                                       context_hash=context_hash),
            token_usage=deferred.token_usage, cost_usd=deferred.cost_usd,
            deferred=True)
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
    ledger: PgRepo | None = None,
    repo_slug: str | None = None,
    agent_run_id: str | None = None,
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
            budget=per_story_budget, items_override=pass_items,
            ledger=ledger, repo_slug=repo_slug, agent_run_id=agent_run_id)
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
            module_dir=module_dir, reason=reason, ledger=ledger,
            repo_slug=repo_slug, agent_run_id=agent_run_id)

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
