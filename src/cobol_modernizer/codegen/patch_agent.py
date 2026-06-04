"""Test-First Patch Agent (Task 4 of the story-sliced codegen engine).

The bounded, per-STORY replacement for the one-shot `generator.py::generate_slice`.
Where `generate_slice` migrates a whole writer slice in a single (long, graph-heavy)
turn-loop, this module generates ONE user story at a time from its already-assembled
`StoryContextPack` — first the failing JUnit5 tests, then the minimal production code
that satisfies them. Task 6's story runner sequences these:

    generate_story_tests -> write tests -> targeted mvn (RED)
    -> generate_story_implementation -> targeted mvn (GREEN) -> repair

Both entry points run TOOL-FREE (allowed_tools=[], server=None): the context pack
already inlines everything the model needs, so there is no graph round-trip (that
matters for the per-story latency budget). The model/turn tiering reuses
`cost/scaling.py`; the timeout + empty-output handling mirror `_run_codegen_call` /
`generate_slice`.

This module is PURE except for the injected `runner` call: NO Neo4j, LLM, or disk
I/O of its own (the caller resolves the pack, writes files, and runs Maven). The
`runner` is typed against the `AgentRunner` Protocol so unit tests inject a stub.
"""
from __future__ import annotations

import logging
import os
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, Field

from cobol_modernizer.agent.harness import AgentRunner
from cobol_modernizer.codegen.schema import GeneratedFile
from cobol_modernizer.enrichment.base import run_batched_result
from cobol_modernizer.codegen.story_context import StoryContextPack
from cobol_modernizer.codegen.story_plan import StoryCodegenItem

logger = logging.getLogger(__name__)


class StoryPatch(BaseModel):
    """Result of one per-story generation pass.

    Returns the filtered `GeneratedFile`s PLUS `rationale` — the one genuinely-new
    field in the model's structured output. The other two story fields in
    `PATCH_SCHEMA` (`story_id`, `acceptance_criteria_ids`) are NOT surfaced here on
    purpose: they steer the model but the Task 6 caller already holds them from the
    `StoryCodegenItem` it passed in. AC traceability itself lives in the written test
    `content` and is recovered downstream by `build.py::scan_generated_test_refs`
    (it greps the test bodies for AC ids), so nothing is lost by not returning it.
    `rationale` IS surfaced so Task 6's runner can persist it in the
    story_codegen_status artifact for telemetry without re-deriving it.
    """

    model_config = {"frozen": True}

    files: list[GeneratedFile] = Field(default_factory=list)
    rationale: str = ""

# Story-scoped budgets. Deliberately DISTINCT env names from the whole-slice
# CODEGEN_* vars so per-story tuning never shadows the legacy generator's knobs.
STORY_CODEGEN_TIMEOUT_S_ENV = "STORY_CODEGEN_TIMEOUT_S"
STORY_CODEGEN_MAX_TURNS_ENV = "STORY_CODEGEN_MAX_TURNS"
STORY_REPAIR_MAX_ATTEMPTS_ENV = "STORY_REPAIR_MAX_ATTEMPTS"
STORY_CODEGEN_ATTEMPTS_ENV = "STORY_CODEGEN_ATTEMPTS"
STORY_CODEGEN_ESCALATE_ENV = "STORY_CODEGEN_ESCALATE"

# Default 120s matches BACKLOG_STORY_TIMEOUT_S: real structured LLM calls on the
# build machine routinely take 51-115s, so a 90s deadline tripped on the first slow
# call. The retry/escalation below (attempts=2, escalate=True) covers residual spikes,
# exactly as the backlog generator drives the same shared `run_batched_result`.
DEFAULT_STORY_TIMEOUT_S = 120.0
DEFAULT_STORY_MAX_TURNS = 2
DEFAULT_STORY_REPAIR_MAX_ATTEMPTS = 2
DEFAULT_STORY_CODEGEN_ATTEMPTS = 2
DEFAULT_STORY_CODEGEN_ESCALATE = True


def story_timeout_s() -> float:
    """Per-story runner timeout (seconds), env-overridable; default 120s."""
    return _env_float(STORY_CODEGEN_TIMEOUT_S_ENV, DEFAULT_STORY_TIMEOUT_S)


def story_max_turns() -> int:
    """Per-story agent turn budget, env-overridable; default 2 (fast path)."""
    return _env_int(STORY_CODEGEN_MAX_TURNS_ENV, DEFAULT_STORY_MAX_TURNS)


def story_codegen_attempts() -> int:
    """Per-story structured-call attempt budget, env-overridable; default 2. With
    attempts=2 a SUCCESS on the first call still makes exactly ONE call (no retry);
    only a RETRYABLE failure (timeout / harness turn-cap) escalates and re-issues."""
    return max(1, _env_int(STORY_CODEGEN_ATTEMPTS_ENV, DEFAULT_STORY_CODEGEN_ATTEMPTS))


def story_codegen_escalate() -> bool:
    """Whether a retried per-story call escalates its timeout/turns (×1.5 each),
    env-overridable; default True. Mirrors the backlog generator's escalation."""
    return _env_bool(STORY_CODEGEN_ESCALATE_ENV, DEFAULT_STORY_CODEGEN_ESCALATE)


def story_repair_max_attempts() -> int:
    """Per-story RED->GREEN repair budget, env-overridable; default 2. Unused in
    THIS module on purpose: it's the knob for Task 6's story runner (which owns the
    write-test -> mvn -> impl -> mvn -> repair loop), exposed here so the env contract
    lives next to its sibling story budgets rather than being defined ad hoc."""
    return _env_int(STORY_REPAIR_MAX_ATTEMPTS_ENV, DEFAULT_STORY_REPAIR_MAX_ATTEMPTS)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Ignoring non-numeric %s=%r; using %.0f", name, raw, default)
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Ignoring non-integer %s=%r; using %d", name, raw, default)
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# Patch schema: the SHAPE of CODEGEN_SCHEMA (files[] with path/kind/content/evidence)
# EXTENDED with the story provenance fields. Files-only — NO arbitrary shell command
# field — so the agent can only ever propose file writes, never execute anything.
PATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "files": {"type": "array", "items": {"type": "object", "properties": {
            "path": {"type": "string"},
            "kind": {"type": "string", "enum": ["test", "main"]},
            "content": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "story_id": {"type": "string"},
            "acceptance_criteria_ids": {"type": "array", "items": {"type": "string"}},
            "rationale": {"type": "string"},
        }, "required": ["path", "kind", "content"]}},
    },
    "required": ["files"],
}


STORY_TESTS_SYSTEM = (
    "You write the FAILING tests for ONE user story using strict TDD. Emit ONLY "
    "JUnit5 test files (kind='test') — NO production code. Your ONLY source of truth "
    "is the story context pack below: its narrative, acceptance criteria, the mapped "
    "domain aggregate (invariants + methods), the technical service (API + "
    "persistence), the BRD requirements, and the inlined COBOL source. Do NOT invent "
    "behavior absent from the pack. Turn EACH acceptance criterion into at least one "
    "concrete failing assertion (prefer one assertion per criterion). EVERY test MUST "
    "cite the story id and the acceptance criterion id(s) it covers — in the test "
    "method name and/or a leading comment, and in the file's evidence/"
    "acceptance_criteria_ids. Target the classes the project scaffold already "
    "declares; do not redefine production types."
)


STORY_IMPL_SYSTEM = (
    "You write the MINIMAL production code that makes ONE story's failing tests pass. "
    "Emit ONLY production files (kind='main') — do NOT emit or modify tests. Write the "
    "least code needed to satisfy the inlined failing tests, grounded ONLY in the "
    "story context pack (its aggregate invariants/methods, technical service, BRD "
    "requirements, and inlined COBOL source). Do NOT invent behavior the tests and "
    "pack do not require (accidental legacy behavior is excluded). Reuse the existing "
    "Java files inlined below rather than re-scaffolding them; patch/extend them where "
    "needed. EVERY file MUST carry the story id and cite the design/BRD/COBOL refs it "
    "is grounded in."
)


def _files_from(raw: dict, *, only: str | None = None) -> list[GeneratedFile]:
    """Coerce the runner's structured payload into GeneratedFile, optionally filtered
    to one kind. The per-file schema also carries story_id/acceptance_criteria_ids/
    rationale; those are dropped at the file level (the file's rationale is folded into
    the StoryPatch by the caller). Projection is explicit because default-config
    pydantic v2 SILENTLY IGNORES extra keys (no extra='forbid'), so `GeneratedFile(**f)`
    would drop them without a trace — projecting the four real fields by name makes
    that drop intentional and visible at the call site."""
    files = [_to_generated_file(f) for f in raw.get("files", [])]
    return [f for f in files if only is None or f.kind == only]


def _to_generated_file(f: dict) -> GeneratedFile:
    return GeneratedFile(
        path=f["path"],
        kind=f["kind"],
        content=f["content"],
        evidence=list(f.get("evidence", [])),
    )


def _rationale_from(raw: dict, *, only: str | None = None) -> str:
    """Join the per-file `rationale` strings the model emitted into one summary,
    scoped to the kept kind so a tests-pass summary doesn't echo the dropped main
    file's rationale (and vice versa). The schema attaches rationale per file (not
    top-level), so we concatenate the distinct, order-preserving non-empty ones."""
    seen: list[str] = []
    for f in raw.get("files", []):
        if only is not None and f.get("kind") != only:
            continue
        r = (f.get("rationale") or "").strip()
        if r and r not in seen:
            seen.append(r)
    return "; ".join(seen)


def _require_files(raw: dict, *, label: str, max_turns: int) -> None:
    """An empty `{}` (runner swallowed an error / hit the turn cap) is an OPERATIONAL
    limit, distinct from a TDD shortfall — raise a clear ValueError, never return []."""
    if not raw.get("files"):
        raise ValueError(
            f"{label} produced no output (likely hit the {max_turns}-turn cap or "
            f"errored — see the harness log; raise {STORY_CODEGEN_MAX_TURNS_ENV}).")


async def _run_story_call(*, runner: AgentRunner, system: str, prompt: str,
                          model: str, max_turns: int, label: str,
                          timeout_s: float, attempts: int, escalate: bool,
                          ) -> dict[str, Any]:
    """Tool-free, schema-bounded runner call routed through the SHARED escalation
    primitive `enrichment.base.run_batched_result` (the same one BACKLOG uses to
    survive this machine's 51-115s structured calls). With `attempts>1` a RETRYABLE
    failure (a timeout, or an empty payload because the harness hit its turn cap) is
    re-issued with an escalated timeout/max_turns (×1.5 each per attempt when
    `escalate`); a SUCCESS on attempt 1 still makes exactly one call.

    `run_batched_result` NEVER raises (it silently degrades to a typed failure), but
    this module's callers (story_runner's try/except) rely on a ValueError contract —
    so we re-raise on `not ok`, preserving the prior `_run_story_call` behavior. An
    `ok` result with an empty `files` list still flows through `_require_files`."""
    # run_batched_result / _run_once already pin the fast path (server=None,
    # allowed_tools=[]); they take no server/allowed_tools args.
    result = await run_batched_result(
        runner=runner, system=system, prompt=prompt,
        model=model, max_turns=max_turns, schema=PATCH_SCHEMA, label=label,
        timeout_s=timeout_s, attempts=attempts, escalate=escalate)
    if not result.ok:
        logger.warning("story codegen %s failed: %s", label, result.cause)
        raise ValueError(f"story codegen {label}: {result.cause}")
    return result.payload


def _project_index_section(project_index: list[str]) -> str:
    if not project_index:
        return ""
    listing = "\n".join(f"- {p}" for p in project_index)
    return (
        "## Project files already scaffolded (do not recreate these)\n"
        f"{listing}\n"
    )


def _ac_ids_section(item: StoryCodegenItem) -> str:
    ids = ", ".join(item.acceptance_criteria_ids) or "(none declared)"
    return (
        f"## Story {item.story_id} — acceptance criterion ids to cite\n"
        f"{ids}\n"
        "Each acceptance criterion MUST become at least one failing assertion, and "
        "every test MUST cite its story id and acceptance criterion id.\n"
    )


def _inline_files_section(title: str, files: list[GeneratedFile]) -> str:
    if not files:
        return ""
    blocks = [title]
    for f in files:
        blocks.append(f"### {f.path}\n```java\n{f.content}\n```")
    return "\n".join(blocks) + "\n"


def _allowed_files_section(allowed_paths: list[str] | None) -> str:
    if not allowed_paths:
        return ""
    listing = "\n".join(f"- {p}" for p in allowed_paths)
    return (
        "## Allowed production files for this story\n"
        f"{listing}\n"
        "Patch ONLY these production files. Do not create new production files, "
        "move files, rename packages, or re-scaffold the project.\n"
    )


def _allowed_test_files_section(allowed_paths: list[str] | None) -> str:
    if not allowed_paths:
        return ""
    listing = "\n".join(f"- {p}" for p in allowed_paths)
    return (
        "## Allowed test files for this story\n"
        f"{listing}\n"
        "Emit tests ONLY in these files. Do not create extra test files or move "
        "tests into another package.\n"
    )


def build_tests_prompt(*, item: StoryCodegenItem, context_pack: StoryContextPack,
                       project_index: list[str],
                       allowed_paths: list[str] | None = None) -> str:
    """Pure prompt assembly for the tests pass (separated so it's unit-testable)."""
    return (
        f"{context_pack.render()}\n\n"
        f"{_ac_ids_section(item)}"
        f"{_project_index_section(project_index)}"
        f"{_allowed_test_files_section(allowed_paths)}"
        "Emit ONLY the failing JUnit5 test files (kind='test') for this story."
    )


def _repair_section(repair_feedback: dict | None) -> str:
    """Render the RED->GREEN repair feedback for a re-generation pass: the failing
    gate + bounded build-log excerpt + the files the previous attempt touched. Mirrors
    `repair_loop.py::run_repair_loop`'s feedback shape (failing gate + log excerpt),
    extended with the touched-file list so the model knows what to patch. Empty string
    on the first (non-repair) pass."""
    if not repair_feedback:
        return ""
    gate = repair_feedback.get("failing_gate", "unknown")
    log = repair_feedback.get("log_excerpt", "") or ""
    touched = repair_feedback.get("touched_files") or []
    lines = [f"## Previous attempt failed gate: {gate}",
             f"## Build log\n```\n{log}\n```"]
    if touched:
        lines.append("## Files your last attempt wrote (patch these)\n"
                     + "\n".join(f"- {p}" for p in touched))
    return "\n".join(lines) + "\nFix the root cause; do not weaken tests.\n"


def build_impl_prompt(*, item: StoryCodegenItem, context_pack: StoryContextPack,
                      failing_tests: list[GeneratedFile],
                      existing_java: list[GeneratedFile],
                      allowed_paths: list[str] | None = None,
                      repair_feedback: dict | None = None) -> str:
    """Pure prompt assembly for the implementation pass. On a repair pass,
    `repair_feedback` (failing gate + log excerpt + touched files) is prepended so the
    re-generation targets the actual failure."""
    return (
        f"{context_pack.render()}\n\n"
        f"{_repair_section(repair_feedback)}"
        f"{_allowed_files_section(allowed_paths)}"
        f"{_inline_files_section('## Failing tests to satisfy', failing_tests)}"
        f"{_inline_files_section('## Existing Java (reuse / patch these)', existing_java)}"
        "Emit ONLY the production files (kind='main') that make the failing tests "
        "above pass."
    )


def _enforce_allowed_paths(files: list[GeneratedFile],
                           allowed_paths: list[str] | None) -> None:
    _enforce_safe_paths(files, label="story implementation")
    if not allowed_paths:
        return
    allowed = {_normalize_generated_path(p) for p in allowed_paths}
    offenders = sorted({
        f.path for f in files if _normalize_generated_path(f.path) not in allowed
    })
    if offenders:
        raise ValueError(
            "story implementation wrote files outside the allowed production scope: "
            + ", ".join(offenders))


def _enforce_allowed_test_paths(files: list[GeneratedFile],
                                allowed_paths: list[str] | None) -> None:
    _enforce_safe_paths(files, label="story tests")
    if not allowed_paths:
        return
    allowed = {_normalize_generated_path(p) for p in allowed_paths}
    offenders = sorted({
        f.path for f in files if _normalize_generated_path(f.path) not in allowed
    })
    if offenders:
        raise ValueError(
            "story tests wrote files outside the allowed test scope: "
            + ", ".join(offenders))


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


def _enforce_safe_paths(files: list[GeneratedFile], *, label: str) -> None:
    for f in files:
        _normalize_generated_path(f.path)


async def generate_story_tests(
    *, runner: AgentRunner, item: StoryCodegenItem,
    context_pack: StoryContextPack, project_index: list[str], model: str,
    allowed_paths: list[str] | None = None,
    max_turns: int | None = None, timeout_s: float | None = None,
    attempts: int | None = None, escalate: bool | None = None,
) -> StoryPatch:
    """Generate the FAILING JUnit5 tests for one story. Returns a `StoryPatch` whose
    `files` are ONLY kind='test', plus the model's `rationale`. Raises ValueError on
    an empty runner payload (turn cap / error) or on an exhausted timeout. Mirrors the
    contract of `generator.py::_emit_tests_only`. `attempts`/`escalate` resolve to the
    STORY_CODEGEN_* env defaults when None (attempts=2, escalate=True) so a slow first
    call is retried with an escalated budget rather than aborting the story."""
    max_turns = story_max_turns() if max_turns is None else max_turns
    timeout_s = story_timeout_s() if timeout_s is None else timeout_s
    attempts = story_codegen_attempts() if attempts is None else attempts
    escalate = story_codegen_escalate() if escalate is None else escalate
    prompt = build_tests_prompt(
        item=item, context_pack=context_pack, project_index=project_index,
        allowed_paths=allowed_paths)
    raw = await _run_story_call(
        runner=runner, system=STORY_TESTS_SYSTEM, prompt=prompt, model=model,
        max_turns=max_turns, label=f"story-tests:{item.story_id}", timeout_s=timeout_s,
        attempts=attempts, escalate=escalate)
    _require_files(raw, label=f"story-tests:{item.story_id}", max_turns=max_turns)
    files = _files_from(raw, only="test")
    _enforce_allowed_test_paths(files, allowed_paths)
    return StoryPatch(
        files=files,
        rationale=_rationale_from(raw, only="test"))


async def generate_story_implementation(
    *, runner: AgentRunner, item: StoryCodegenItem,
    context_pack: StoryContextPack, failing_tests: list[GeneratedFile],
    existing_java: list[GeneratedFile], model: str,
    allowed_paths: list[str] | None = None,
    max_turns: int | None = None, timeout_s: float | None = None,
    attempts: int | None = None, escalate: bool | None = None,
    repair_feedback: dict | None = None,
) -> StoryPatch:
    """Generate the MINIMAL production code that satisfies one story's failing tests.
    Returns a `StoryPatch` whose `files` are ONLY kind='main', plus the model's
    `rationale`. Raises ValueError on an empty runner payload or an exhausted timeout.
    The bounded, per-story analogue of `generate_slice`'s production pass. On a repair
    re-generation, `repair_feedback` (failing gate + build-log excerpt + the touched
    files) is folded into the prompt, mirroring `repair_loop.py`. `attempts`/`escalate`
    resolve to the STORY_CODEGEN_* env defaults (attempts=2, escalate=True) when None."""
    max_turns = story_max_turns() if max_turns is None else max_turns
    timeout_s = story_timeout_s() if timeout_s is None else timeout_s
    attempts = story_codegen_attempts() if attempts is None else attempts
    escalate = story_codegen_escalate() if escalate is None else escalate
    if allowed_paths is None and existing_java:
        allowed_paths = [f.path for f in existing_java]
    prompt = build_impl_prompt(
        item=item, context_pack=context_pack, failing_tests=failing_tests,
        existing_java=existing_java, allowed_paths=allowed_paths,
        repair_feedback=repair_feedback)
    raw = await _run_story_call(
        runner=runner, system=STORY_IMPL_SYSTEM, prompt=prompt, model=model,
        max_turns=max_turns, label=f"story-impl:{item.story_id}", timeout_s=timeout_s,
        attempts=attempts, escalate=escalate)
    _require_files(raw, label=f"story-impl:{item.story_id}", max_turns=max_turns)
    files = _files_from(raw, only="main")
    _enforce_allowed_paths(files, allowed_paths)
    return StoryPatch(
        files=files,
        rationale=_rationale_from(raw, only="main"))
