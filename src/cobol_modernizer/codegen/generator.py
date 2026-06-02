"""TDD codegen agent. Works PRIMARILY from the brief — the DDD/OO domain design and
BRD requirements — plus the slice source the caller inlines; the read-only context
graph is a last-resort lookup, not the main input (it's the verification stage that
leans on the graph). Emits failing tests THEN production code; each file carries
lineage. role='codegen' (Sonnet) via the foundation harness (tools=[], json_schema).

A single agent occasionally emits production code but skips the tests (weaker tiers
do this under graph-exploration pressure). Rather than discard a multi-minute run,
the engine runs a focused *repair* pass that asks ONLY for the missing failing
tests, then merges them ahead of the code — so TDD is recovered, not re-run."""
from __future__ import annotations

import logging
from typing import Any

from cobol_modernizer.codegen.schema import GeneratedFile, GeneratedProject

logger = logging.getLogger(__name__)

CODEGEN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "files": {"type": "array", "items": {"type": "object", "properties": {
            "path": {"type": "string"},
            "kind": {"type": "string", "enum": ["test", "main"]},
            "content": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}},
        }, "required": ["path", "kind", "content"]}},
    },
    "required": ["files"],
}

CODEGEN_SYSTEM = (
    "You migrate ONE COBOL writer slice to Spring Boot using strict TDD. Your PRIMARY "
    "sources of truth are, in order: (1) the DDD/OO domain design in the brief — its "
    "bounded contexts, aggregates with invariants and methods, value objects, domain "
    "services, and api_surface; (2) the BRD requirements; (3) the slice source inlined "
    "below the brief. Design and requirements drive the code; the inlined source is "
    "for detail. The read-only graph tools are a LAST RESORT — call one ONLY to "
    "resolve a specific reference that is genuinely missing from the brief and the "
    "inlined source; do NOT explore the graph to 'understand' the slice (that wastes "
    "turns and the design already captures it). FIRST emit JUnit5 tests (kind='test') "
    "that turn each aggregate invariant, method, and api_surface entry — plus the BRD "
    "requirements — into a concrete failing assertion; THEN emit the minimal "
    "production code (kind='main') modelled on the design's aggregates and services. "
    "Every file MUST list the design/BRD refs (and any graph entity ids) it is "
    "grounded in. Do NOT invent behavior absent from the BRD/design (accidental legacy "
    "behavior is excluded). "
    "If backlog stories are present, every acceptance criterion MUST become at least "
    "one JUnit assertion and the generated test evidence MUST cite the story id and "
    "acceptance criterion id."
)


TESTS_ONLY_SYSTEM = (
    "You are completing a strict-TDD migration that already drafted the production "
    "code but is MISSING its failing tests. Emit ONLY JUnit5 test files (kind='test') "
    "— no production code. Work from the DDD/OO domain design and BRD requirements in "
    "the brief (the graph tools are a LAST RESORT, only for a reference missing from "
    "the brief and inlined source): turn each aggregate invariant, method, and "
    "api_surface entry, plus the BRD requirements, into a failing assertion against "
    "the drafted classes. Every test MUST list the design/BRD refs it is grounded in."
)


def _files_from(raw: dict, *, only: str | None = None) -> list[GeneratedFile]:
    files = [GeneratedFile(**f) for f in raw.get("files", [])]
    return [f for f in files if only is None or f.kind == only]


def _evidence_map(files: list[GeneratedFile]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for f in files:
        for ref in f.evidence:
            out.setdefault(ref, []).append(f.path)
    return out


def _mains_digest(mains: list[GeneratedFile]) -> str:
    """Compact view of the drafted production files so the repair pass can write
    tests that target the right classes/paths without re-deriving them."""
    return "\n".join(f"- {f.path} (evidence: {', '.join(f.evidence) or 'none'})"
                     for f in mains) or "(none drafted)"


async def _emit_tests_only(*, runner, server, model: str, brd_json: str,
                           golden_summary: str, allowed_tools: list[str],
                           max_turns: int, mains: list[GeneratedFile],
                           source_pack: str = "") -> list[GeneratedFile]:
    prompt = (
        f"## Migration brief — BRD requirements + DDD/OO domain design\n"
        f"```json\n{brd_json}\n```\n"
        f"## Golden-master summary (the oracle)\n{golden_summary}\n"
        f"{_source_pack_section(source_pack)}"
        f"## Production code already drafted (write the failing tests that pin it)\n"
        f"{_mains_digest(mains)}\n"
        "Emit ONLY the missing failing test files (kind='test')."
    )
    raw = await runner.run_structured(
        system=TESTS_ONLY_SYSTEM, prompt=prompt, server=server,
        allowed_tools=allowed_tools, model=model, max_turns=max_turns,
        schema=CODEGEN_SCHEMA, label="codegen-test-repair")
    return _files_from(raw, only="test")


def _source_pack_section(source_pack: str) -> str:
    """When the caller has pre-materialized the slice source (scoped to the design's
    entities, so bounded at any repo size), inline it so the agent writes directly
    instead of paying a graph round-trip per entity."""
    if not source_pack.strip():
        return ""
    return (
        "## Slice source — COMPLETE (pre-fetched for you)\n"
        f"{source_pack}\n"
        "The full source of the slice is above; you should NOT need graph exploration "
        "— emit the files directly. Use the graph tools only to resolve a specific "
        "reference you cannot find above.\n"
    )


async def generate_slice(*, runner, server, model: str, brd_json: str,
                         golden_summary: str, allowed_tools: list[str],
                         max_turns: int = 40, repair_attempts: int = 2,
                         source_pack: str = "") -> GeneratedProject:
    prompt = (
        f"## Migration brief — BRD requirements + DDD/OO domain design\n"
        f"```json\n{brd_json}\n```\n"
        f"## Golden-master summary (the oracle)\n{golden_summary}\n"
        f"{_source_pack_section(source_pack)}"
        "Emit the failing tests first (assert the domain design's invariants and "
        "api_surface), then the code. "
        "If the brief includes backlog stories, convert their acceptance criteria into "
        "tests before writing production code."
    )
    raw = await runner.run_structured(
        system=CODEGEN_SYSTEM, prompt=prompt, server=server,
        allowed_tools=allowed_tools, model=model, max_turns=max_turns,
        schema=CODEGEN_SCHEMA, label="codegen")
    files = _files_from(raw)
    # Distinguish "the agent returned nothing" (hit the turn cap / errored — the
    # runner swallows it to {}) from a TDD shortfall (emitted code but no test). The
    # first is an operational limit; the second is recoverable via a repair pass.
    if not files:
        raise ValueError(
            f"codegen agent produced no output (likely hit the {max_turns}-turn cap "
            "or errored — see the harness log; raise CODEGEN_AGENT_MAX_TURNS).")

    tests = [f for f in files if f.kind == "test"]
    mains = [f for f in files if f.kind == "main"]
    for attempt in range(1, repair_attempts + 1):
        if tests:
            break
        logger.warning(
            "codegen emitted %d file(s) but no test (kinds=%s) — TDD repair %d/%d: "
            "asking only for the missing failing tests",
            len(files), [f.kind for f in files], attempt, repair_attempts)
        tests = await _emit_tests_only(
            runner=runner, server=server, model=model, brd_json=brd_json,
            golden_summary=golden_summary, allowed_tools=allowed_tools,
            max_turns=max_turns, mains=mains, source_pack=source_pack)

    if not tests:
        raise ValueError(
            f"codegen produced no failing test (TDD violated) after {repair_attempts} "
            f"repair attempt(s); the agent only emitted {[f.kind for f in mains]}.")

    files = tests + mains  # tests first — the TDD invariant downstream relies on
    return GeneratedProject(files=files, evidence_map=_evidence_map(files))
