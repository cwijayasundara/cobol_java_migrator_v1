"""Batched design enrichment (net-new — no prior LLM design path): for each writer
slice, elaborate the template ADRs (richer context/decision/consequences +
alternatives), describe the Java components, sketch the API surface, and note the data
model — grounded in the slice's owned resources + program refs."""
from __future__ import annotations

import json
from typing import Any

from cobol_modernizer.enrichment.base import ground_refs, run_batched
from cobol_modernizer.enrichment.schema import DesignADR, DesignNarrative

DESIGN_SYSTEM = (
    "You elaborate a precomputed service design for EACH writer slice. For each slice: "
    "expand its ADRs (context, decision, consequences, alternatives), describe each "
    "Java component's responsibility, sketch the API surface, and note how the owned "
    "mainframe resources map to the data model. Ground everything ONLY in the slice's "
    "owned_resources + evidence refs; cite refs in 'cited_refs'; invent no identifiers. "
    'Return JSON: {"items":[{"slice_id","adrs":[{"number","title","context","decision",'
    '"consequences","alternatives"}],"component_descriptions":[str],"api_surface",'
    '"data_model_notes","cited_refs":[str]}...]}.'
)

DESIGN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
        "slice_id": {"type": "string"},
        "adrs": {"type": "array", "items": {"type": "object", "properties": {
            "number": {"type": "integer"}, "title": {"type": "string"},
            "context": {"type": "string"}, "decision": {"type": "string"},
            "consequences": {"type": "string"}, "alternatives": {"type": "string"}},
            "required": ["number", "title"]}},
        "component_descriptions": {"type": "array", "items": {"type": "string"}},
        "api_surface": {"type": "string"}, "data_model_notes": {"type": "string"},
        "cited_refs": {"type": "array", "items": {"type": "string"}}},
        "required": ["slice_id"]}}},
    "required": ["items"],
}


def _parse_adrs(raw: Any) -> list[DesignADR]:
    out: list[DesignADR] = []
    for a in raw or []:
        if not isinstance(a, dict):
            continue
        try:
            num = int(a.get("number"))
        except (TypeError, ValueError):
            continue
        title = a.get("title")
        if not isinstance(title, str):
            continue
        out.append(DesignADR(number=num, title=title,
                             context=str(a.get("context", "")),
                             decision=str(a.get("decision", "")),
                             consequences=str(a.get("consequences", "")),
                             alternatives=str(a.get("alternatives", ""))))
    return out


async def enrich_design(designs: list[dict], known_refs: set[str], *,
                        runner, model: str, timeout_s: float) -> dict[str, dict]:
    if not designs:
        return {}
    valid = {d["slice_id"] for d in designs if d.get("slice_id")}
    prompt = ("## Precomputed writer-slice designs\n```json\n" + json.dumps(designs)
              + "\n```\nElaborate each slice grounded only in its resources/refs.")
    raw = await run_batched(runner=runner, system=DESIGN_SYSTEM, prompt=prompt,
                            schema=DESIGN_SCHEMA, model=model, timeout_s=timeout_s,
                            label="enrich-design")
    out: dict[str, dict] = {}
    for item in raw.get("items", []):
        if not isinstance(item, dict):
            continue
        sid = item.get("slice_id")
        if not isinstance(sid, str) or sid not in valid:
            continue
        cited, _grounded = ground_refs(item.get("cited_refs"), known_refs)
        comps = [c for c in (item.get("component_descriptions") or [])
                 if isinstance(c, str)]
        out[sid] = DesignNarrative(
            slice_id=sid, adrs=_parse_adrs(item.get("adrs")),
            component_descriptions=comps,
            api_surface=str(item.get("api_surface", "")),
            data_model_notes=str(item.get("data_model_notes", "")),
            cited_refs=cited).model_dump()
    return out
