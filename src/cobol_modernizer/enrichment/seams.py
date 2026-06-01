"""Batched seam-rationale enrichment: ONE structured call explains WHY each
precomputed seam ranks where it does, grounded only in the provided evidence refs.
Generalizes seam/rationale.py:awrite_rationale from per-candidate to one batched call."""
from __future__ import annotations

import json
from typing import Any

from cobol_modernizer.enrichment.base import ground_refs, run_batched
from cobol_modernizer.enrichment.schema import SeamNarrative

SEAMS_SYSTEM = (
    "You explain WHY each precomputed seam ranking is what it is. You DO NOT score. "
    "For EACH seam, write a 1-2 sentence rationale (why it ranks here + the main "
    "migration risk), grounded ONLY in the provided evidence refs. Cite the exact "
    "refs you used in 'cited_refs'. Do not invent identifiers. Return JSON: "
    '{"items":[{"program","rationale","cited_refs":[str]}...]}.'
)

SEAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {"type": "object",
        "properties": {"program": {"type": "string"},
                       "rationale": {"type": "string"},
                       "cited_refs": {"type": "array", "items": {"type": "string"}}},
        "required": ["program"]}}},
    "required": ["items"],
}


async def enrich_seams(candidates: list[dict], known_refs: set[str], *,
                       runner, model: str, timeout_s: float) -> dict[str, dict]:
    if not candidates:
        return {}
    valid = {c["program"] for c in candidates if c.get("program")}
    payload = [{"program": c.get("program"), "seam_type": c.get("seam_type"),
                "signals": c.get("signals"), "score": c.get("score"),
                "evidence_map": c.get("evidence_map", {})} for c in candidates]
    prompt = ("## Precomputed seam candidates (signal scores + evidence)\n```json\n"
              + json.dumps(payload) + "\n```\nExplain each ranking using only its refs.")
    raw = await run_batched(runner=runner, system=SEAMS_SYSTEM, prompt=prompt,
                            schema=SEAMS_SCHEMA, model=model, timeout_s=timeout_s,
                            label="enrich-seams")
    out: dict[str, dict] = {}
    for item in raw.get("items", []):
        if not isinstance(item, dict):
            continue
        prog = item.get("program")
        if not isinstance(prog, str) or prog not in valid:
            continue
        grounded_refs, grounded = ground_refs(item.get("cited_refs"), known_refs)
        out[prog] = SeamNarrative(program=prog,
                                  rationale=str(item.get("rationale", "")),
                                  cited_refs=grounded_refs,
                                  grounded=grounded).model_dump()
    return out
