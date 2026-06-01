"""TDD codegen agent. Reads BRD + golden-fixture summary + read-only graph
slices; emits failing tests THEN production code. Each file carries lineage.
role='codegen' (Sonnet) via the foundation harness (tools=[], json_schema)."""
from __future__ import annotations

from typing import Any

from cobol_modernizer.codegen.schema import GeneratedFile, GeneratedProject

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
    "You migrate ONE COBOL writer slice to Spring Boot using strict TDD. "
    "FIRST emit JUnit5 tests that assert the BRD's required behavior against the "
    "golden fixtures (kind='test'); THEN emit the minimal production code "
    "(kind='main'). Use ONLY the read-only graph tools and the supplied evidence; "
    "every file MUST list the graph entity ids it is grounded in. Do NOT invent "
    "behavior absent from the BRD (accidental legacy behavior is excluded)."
)


async def generate_slice(*, runner, server, model: str, brd_json: str,
                         golden_summary: str, allowed_tools: list[str],
                         max_turns: int = 40) -> GeneratedProject:
    prompt = (
        f"## BRD\n```json\n{brd_json}\n```\n"
        f"## Golden-master summary (the oracle)\n{golden_summary}\n"
        "Emit tests first, then code."
    )
    raw = await runner.run_structured(
        system=CODEGEN_SYSTEM, prompt=prompt, server=server,
        allowed_tools=allowed_tools, model=model, max_turns=max_turns,
        schema=CODEGEN_SCHEMA)
    files = [GeneratedFile(**f) for f in raw.get("files", [])]
    # Distinguish "the agent returned nothing" (hit the turn cap / errored — the
    # runner swallows it to {}) from a genuine TDD violation (emitted code but no
    # test). The first is an operational limit, not a discipline failure.
    if not files:
        raise ValueError(
            f"codegen agent produced no output (likely hit the {max_turns}-turn cap "
            "or errored — see the harness log; raise CODEGEN_AGENT_MAX_TURNS).")
    if not any(f.kind == "test" for f in files):
        raise ValueError("codegen produced no failing test (TDD violated)")
    evidence_map: dict[str, list[str]] = {}
    for f in files:
        for ref in f.evidence:
            evidence_map.setdefault(ref, []).append(f.path)
    return GeneratedProject(files=files, evidence_map=evidence_map)
