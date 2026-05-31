from __future__ import annotations

import json
from typing import Any

from cobol_modernizer.agent import graph_ops as ops
from cobol_modernizer.agent.deps import GraphDeps
from cobol_modernizer.agent.harness import AgentRunner
from cobol_modernizer.brd.schema import (
    BRD, Dimension, DimensionScore, FeedbackItem, JudgeReport, Rating,
)

WEIGHTS = {
    Dimension.completeness: 0.25, Dimension.accuracy: 0.30, Dimension.clarity: 0.15,
    Dimension.consistency: 0.15, Dimension.actionability: 0.15,
}

JUDGE_SYSTEM = """Evaluate this BRD generated from a codebase. Score five dimensions
1-5 each with a brief rationale: completeness, accuracy, clarity, consistency,
actionability. Return JSON: {"items":[{"dimension","score","rationale"}...],
"feedback":[{"dimension","severity","suggestion","target_section"}...]}."""

# Reuse the LLM output schema shape for output_format.
_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {"type": "array", "items": {"type": "object", "properties": {
            "dimension": {"type": "string"}, "score": {"type": "integer"},
            "rationale": {"type": "string"}}, "required": ["dimension", "score"]}},
        "feedback": {"type": "array", "items": {"type": "object", "properties": {
            "dimension": {"type": "string"}, "severity": {"type": "string"},
            "suggestion": {"type": "string"}, "target_section": {"type": "string"}}}},
    },
    "required": ["items"],
}


def _groundedness_failures(brd: BRD, known: set[str]) -> list[str]:
    failures: list[str] = []
    for refs in brd.evidence_map.values():
        for ref in refs:
            if ref not in known:
                failures.append(ref)
    return failures


def _rate(weighted: float, dims: dict[Dimension, DimensionScore]) -> Rating:
    if weighted >= 4.2 and all(d.score >= 3 for d in dims.values()):
        return Rating.high
    if weighted >= 3.2 and all(d.score >= 2 for d in dims.values()):
        return Rating.medium
    return Rating.low


async def ajudge(brd: BRD, deps: GraphDeps, *, runner: AgentRunner,
                 model: str) -> JudgeReport:
    known = ops.known_refs(deps)
    failures = _groundedness_failures(brd, known)

    raw: dict[str, Any] = await runner.run_structured(
        system=JUDGE_SYSTEM,
        prompt="## BRD under review\n```json\n" + brd.model_dump_json() + "\n```",
        server=None, allowed_tools=[], model=model, max_turns=1, schema=_JUDGE_SCHEMA,
    )

    dims: dict[Dimension, DimensionScore] = {}
    for item in raw.get("items", []):
        try:
            dim = Dimension(item["dimension"])
        except ValueError:
            continue
        dims[dim] = DimensionScore(score=int(item["score"]),
                                   rationale=item.get("rationale", ""))
    for d in Dimension:                      # default any missing dimension to 3
        dims.setdefault(d, DimensionScore(score=3, rationale="(not scored)"))

    if failures and dims[Dimension.accuracy].score > 2:
        prev = dims[Dimension.accuracy]
        dims[Dimension.accuracy] = DimensionScore(
            score=2,
            rationale=prev.rationale + f" [forced to 2 by hallucinated refs: {failures}]")

    weighted = sum(dims[d].score * w for d, w in WEIGHTS.items())
    feedback = [FeedbackItem(**f) for f in raw.get("feedback", [])
                if {"dimension", "severity", "suggestion", "target_section"} <= set(f)]
    return JudgeReport(dimensions=dims, weighted_score=weighted,
                       rating=_rate(weighted, dims), feedback=feedback,
                       groundedness_failures=failures)
