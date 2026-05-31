"""Design gate: a service must own its data, and every evidence ref must exist
in the graph. Mirrors the BRD groundedness gate (brd_judge.py): hallucinated
refs floor the rating to 'low'; an ownership leak floors it to 'low'."""
from __future__ import annotations

from pydantic import BaseModel

from cobol_modernizer.design.schema import ServiceDesign


class DesignJudgeReport(BaseModel):
    data_ownership_ok: bool
    groundedness_failures: list[str]
    rating: str            # high | medium | low
    weighted_score: float
    rationale: str


def judge_design(design: ServiceDesign, *, known_refs: set[str],
                 external_writers: dict[str, list[str]]) -> DesignJudgeReport:
    # 1. Groundedness: every evidence ref must be a known graph entity.
    failures: list[str] = []
    for refs in design.evidence_map.values():
        for ref in refs:
            if ref not in known_refs:
                failures.append(ref)

    # 2. Data-ownership: no owned resource may also be written by another context.
    leaks = [r for r in design.owned_resources if external_writers.get(r)]
    data_ownership_ok = not leaks

    if failures:
        return DesignJudgeReport(
            data_ownership_ok=data_ownership_ok, groundedness_failures=failures,
            rating="low", weighted_score=2.0,
            rationale=f"hallucinated evidence refs: {failures}")
    if not data_ownership_ok:
        return DesignJudgeReport(
            data_ownership_ok=False, groundedness_failures=[],
            rating="low", weighted_score=2.0,
            rationale=f"ownership leak; shared writers: "
                      f"{ {r: external_writers[r] for r in leaks} }")
    return DesignJudgeReport(
        data_ownership_ok=True, groundedness_failures=[],
        rating="high", weighted_score=4.4,
        rationale="service owns its data; all evidence grounded")
