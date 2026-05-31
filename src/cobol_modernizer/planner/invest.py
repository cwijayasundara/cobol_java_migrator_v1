from __future__ import annotations

from typing import Any

INVEST_SYSTEM = (
    "Score this migration story on the six INVEST dimensions 1-5: independent, "
    "negotiable, valuable, estimable, small, testable. Base 'valuable'/'estimable' "
    "ONLY on the cited seam evidence. "
    'Return JSON: {"independent","negotiable","valuable","estimable","small","testable"}.'
)

INVEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {d: {"type": "integer"} for d in
                   ("independent", "negotiable", "valuable", "estimable", "small", "testable")},
    "required": ["independent", "negotiable", "valuable", "estimable", "small", "testable"],
}

_DIMS = ("independent", "negotiable", "valuable", "estimable", "small", "testable")
_PASS_MIN = 3   # every dimension must be >= 3 to pass


async def judge_story(story, *, known_refs: set[str], runner, model: str) -> dict[str, Any]:
    refs = [r for refs in story.evidence_map.values() for r in refs]
    failures = sorted({r for r in refs if r not in known_refs})

    raw = await runner.run_structured(
        system=INVEST_SYSTEM,
        prompt=f"## Story\n```json\n{story.model_dump_json()}\n```",
        server=None, allowed_tools=[], model=model, max_turns=1, schema=INVEST_SCHEMA)

    invest = {d: int(raw.get(d, 3)) for d in _DIMS}
    if failures:                       # groundedness floor: ungrounded value/estimate
        invest["valuable"] = min(invest["valuable"], 2)
        invest["estimable"] = min(invest["estimable"], 2)
    passed = not failures and all(v >= _PASS_MIN for v in invest.values())
    return {"invest": invest, "groundedness_failures": failures, "passed": passed}
