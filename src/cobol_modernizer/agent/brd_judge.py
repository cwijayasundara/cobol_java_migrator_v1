from __future__ import annotations

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


_VALID_SEVERITIES = {"low", "medium", "high"}


def _norm_dimension(value: Any) -> Dimension | None:
    """Map a model-emitted dimension string to the Dimension enum, tolerant of
    case/whitespace drift (e.g. 'Completeness' -> completeness). Weaker/cheaper
    judge models don't always echo the exact lowercase enum value, and an
    unhandled mismatch used to crash the whole BRD run."""
    if not isinstance(value, str):
        return None
    try:
        return Dimension(value.strip().lower())
    except ValueError:
        return None


def _coerce_score(value: Any) -> int | None:
    """Parse a 1-5 score, clamping out-of-range and rejecting non-numeric input,
    so a malformed score can't raise out of the parsing loop."""
    try:
        return max(1, min(5, int(value)))
    except (TypeError, ValueError):
        return None


def _parse_feedback(raw_feedback: Any) -> list[FeedbackItem]:
    """Build FeedbackItems defensively: normalize the dimension/severity casing
    and SKIP any item that's still malformed rather than letting one bad entry
    (a too-common failure mode for cheaper judge models) abort the run."""
    out: list[FeedbackItem] = []
    for f in raw_feedback or []:
        if not isinstance(f, dict):
            continue
        dim = _norm_dimension(f.get("dimension"))
        severity = str(f.get("severity", "")).strip().lower()
        if dim is None or severity not in _VALID_SEVERITIES:
            continue
        suggestion, target = f.get("suggestion"), f.get("target_section")
        if not isinstance(suggestion, str) or not isinstance(target, str):
            continue
        out.append(FeedbackItem(dimension=dim, severity=severity,
                                suggestion=suggestion, target_section=target))
    return out


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
        # max_turns must be >=2: under claude-agent-sdk 0.2.87 emitting the
        # structured-output result consumes a turn, so max_turns=1 always errors
        # with "Reached maximum number of turns (1)" and the judge gets {} (-> low).
        server=None, allowed_tools=[], model=model, max_turns=2, schema=_JUDGE_SCHEMA,
        label="brd-judge",
    )

    dims: dict[Dimension, DimensionScore] = {}
    for item in raw.get("items", []):
        if not isinstance(item, dict):
            continue
        dim = _norm_dimension(item.get("dimension"))
        score = _coerce_score(item.get("score"))
        if dim is None or score is None:     # drop unparseable rows, don't crash
            continue
        dims[dim] = DimensionScore(score=score, rationale=item.get("rationale", ""))
    for d in Dimension:                      # default any missing dimension to 3
        dims.setdefault(d, DimensionScore(score=3, rationale="(not scored)"))

    if failures and dims[Dimension.accuracy].score > 2:
        prev = dims[Dimension.accuracy]
        dims[Dimension.accuracy] = DimensionScore(
            score=2,
            rationale=prev.rationale + f" [forced to 2 by hallucinated refs: {failures}]")

    weighted = sum(dims[d].score * w for d, w in WEIGHTS.items())
    feedback = _parse_feedback(raw.get("feedback"))
    return JudgeReport(dimensions=dims, weighted_score=weighted,
                       rating=_rate(weighted, dims), feedback=feedback,
                       groundedness_failures=failures)
