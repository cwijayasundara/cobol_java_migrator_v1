"""Pick the thin-slice program from the Phase-1 seam ranking.

CRITICAL (master plan §1.4, §4.2): seam scoring is computed in Cypher/GDS
(Phase 1 `seam_candidates`). This module does NOT re-score and does NOT call an
LLM — it only applies the deterministic strangler-fig policy 'macro before micro,
one verified seam before broadening': choose the safest reader-only seam first.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SliceChoice:
    program: str
    reader_only: bool
    score: float
    evidence: dict  # the deterministic Cypher signals (fan_in/fan_out/reads/writes)


def pick_slice(candidates: list[dict]) -> SliceChoice:
    """Choose the first verified seam: the highest-scoring reader-only program.

    Tie-break: higher score, then lower fan_out (less blast radius), then name.
    Raises ValueError if no reader-only candidate exists (a writer-first slice
    violates the Phase-2 'low-fan-in read-only' precondition; writers are Phase 5).
    """
    readers = [c for c in candidates if c.get("reader_only") is True]
    if not readers:
        raise ValueError("no reader-only seam in candidates; cannot start a "
                         "read-only thin slice (writer slices are Phase 5)")
    readers.sort(key=lambda c: (-float(c["score"]), int(c["fan_out"]), c["program"]))
    top = readers[0]
    return SliceChoice(
        program=top["program"],
        reader_only=True,
        score=float(top["score"]),
        evidence={"fan_in": int(top["fan_in"]), "fan_out": int(top["fan_out"]),
                  "reads": int(top["reads"]), "writes": int(top["writes"])},
    )
