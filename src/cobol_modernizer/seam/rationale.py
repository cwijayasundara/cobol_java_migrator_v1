from __future__ import annotations

import json
from typing import Any

RATIONALE_SYSTEM = (
    "You explain WHY a precomputed seam ranking is what it is. You DO NOT score. "
    "Write a 1-2 sentence rationale grounded ONLY in the provided evidence refs. "
    "Cite the exact refs you used in 'cited_refs'. Do not invent identifiers. "
    'Return JSON: {"rationale": str, "cited_refs": [str]}.'
)

RATIONALE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rationale": {"type": "string"},
        "cited_refs": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["rationale", "cited_refs"],
}


async def awrite_rationale(*, program: str, evidence: dict[str, list[str]],
                           known_refs: set[str], runner, model: str) -> dict[str, Any]:
    prompt = (f"## Seam: {program}\n## Precomputed evidence (signal -> refs)\n"
              f"```json\n{json.dumps(evidence)}\n```\n"
              "Explain the ranking using only these refs.")
    raw = await runner.run_structured(
        system=RATIONALE_SYSTEM, prompt=prompt, server=None, allowed_tools=[],
        model=model, max_turns=1, schema=RATIONALE_SCHEMA)
    cited = [r for r in raw.get("cited_refs", []) if isinstance(r, str)]
    grounded_refs = [r for r in cited if r in known_refs]
    return {
        "rationale": raw.get("rationale", ""),
        "cited_refs": grounded_refs,
        "grounded": len(grounded_refs) == len(cited) and len(cited) > 0,
    }
