"""Batched plan enrichment: per-story INVEST + description + acceptance criteria AND
a plan-level delivery narrative (dependency-edge rationale + per-wave guidance). One
structured call. Reuses the INVEST groundedness floor from planner/invest.py:
ungrounded evidence caps 'valuable'/'estimable' at 2."""
from __future__ import annotations

import json
from typing import Any

from cobol_modernizer.enrichment.base import run_batched
from cobol_modernizer.enrichment.schema import (
    PlanDeliveryNarrative, StoryNarrative, WaveNote,
)

_DIMS = ("independent", "negotiable", "valuable", "estimable", "small", "testable")

PLAN_SYSTEM = (
    "You enrich a migration delivery plan. (1) For EACH story, score the six INVEST "
    "dimensions 1-5, write a 1-2 sentence description, and 1-3 acceptance criteria. "
    "(2) For the DELIVERY plan: explain each dependency edge (why it exists) and, for "
    "each wave, what it delivers / de-risks (readers-before-writers, blast radius). "
    "Ground value/estimate ONLY in the story's evidence refs. Return JSON: "
    '{"stories":[{"story_id","invest":{...6 dims...},"description","acceptance_criteria":[str]}...],'
    '"edge_rationale":{"S2->S1":str,...},"wave_narrative":[{"wave":int,"narrative":str}...]}.'
)

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "stories": {"type": "array", "items": {"type": "object", "properties": {
            "story_id": {"type": "string"},
            "invest": {"type": "object",
                       "properties": {d: {"type": "integer"} for d in _DIMS}},
            "description": {"type": "string"},
            "acceptance_criteria": {"type": "array", "items": {"type": "string"}}},
            "required": ["story_id"]}},
        "edge_rationale": {"type": "object", "additionalProperties": {"type": "string"}},
        "wave_narrative": {"type": "array", "items": {"type": "object", "properties": {
            "wave": {"type": "integer"}, "narrative": {"type": "string"}}}},
    },
    "required": ["stories"],
}


def _coerce_invest(raw: Any) -> dict[str, int]:
    raw = raw if isinstance(raw, dict) else {}
    out: dict[str, int] = {}
    for d in _DIMS:
        try:
            out[d] = max(1, min(5, int(raw.get(d, 3))))
        except (TypeError, ValueError):
            out[d] = 3
    return out


async def enrich_plan(stories: list[dict], waves: list[list[str]],
                      known_refs: set[str], *, runner, model: str,
                      timeout_s: float) -> dict[str, Any]:
    if not stories:
        return {"stories": {}, "delivery": PlanDeliveryNarrative().model_dump()}
    valid = {s["id"] for s in stories if s.get("id")}
    refs_by_story = {s["id"]: [r for refs in (s.get("evidence_map") or {}).values()
                               for r in refs] for s in stories}
    prompt = ("## Stories\n```json\n" + json.dumps(stories) + "\n```\n"
              "## Delivery waves (parallel tracks)\n```json\n" + json.dumps(waves)
              + "\n```\nEnrich each story and the delivery plan.")
    raw = await run_batched(runner=runner, system=PLAN_SYSTEM, prompt=prompt,
                            schema=PLAN_SCHEMA, model=model, timeout_s=timeout_s,
                            label="enrich-plan")

    story_out: dict[str, dict] = {}
    for item in raw.get("stories", []):
        if not isinstance(item, dict):
            continue
        sid = item.get("story_id")
        if not isinstance(sid, str) or sid not in valid:
            continue
        invest = _coerce_invest(item.get("invest"))
        failures = sorted({r for r in refs_by_story.get(sid, []) if r not in known_refs})
        if failures:
            invest["valuable"] = min(invest["valuable"], 2)
            invest["estimable"] = min(invest["estimable"], 2)
        crit = [c for c in (item.get("acceptance_criteria") or []) if isinstance(c, str)]
        story_out[sid] = StoryNarrative(
            story_id=sid, invest=invest, description=str(item.get("description", "")),
            acceptance_criteria=crit, groundedness_failures=failures).model_dump()

    edges = {k: str(v) for k, v in (raw.get("edge_rationale") or {}).items()
             if isinstance(k, str) and isinstance(v, str)}
    notes = [WaveNote(wave=int(w.get("wave", 0)), narrative=str(w.get("narrative", "")))
             for w in (raw.get("wave_narrative") or []) if isinstance(w, dict)]
    delivery = PlanDeliveryNarrative(edge_rationale=edges, wave_narrative=notes)
    return {"stories": story_out, "delivery": delivery.model_dump()}
