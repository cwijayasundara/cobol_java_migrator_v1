"""Deterministic seam scoring. Pure facade over Cypher results (CodeGraphQueries).
ZERO LLM in this module — the LLM only writes rationale over these candidates
later (master-plan §1.4, §4.2). Every candidate carries an evidence_map
(lineage) per the Foundation evidence_map contract."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SeamCandidate:
    program: str
    fan_in: int
    fan_out: int
    write_count: int
    side_effects: int
    reader_only: bool
    score: float
    evidence_map: dict[str, list[str]] = field(default_factory=dict)


class SeamScorer:
    def __init__(self, queries, repo: str | None = None) -> None:
        self._q = queries
        self._repo = repo

    def rank(self, limit: int = 20) -> list[SeamCandidate]:
        rows = self._q.seam_candidates(repo=self._repo, limit=limit)
        out: list[SeamCandidate] = []
        for r in rows:
            prog = r["program"]
            out.append(SeamCandidate(
                program=prog,
                fan_in=int(r["fan_in"]),
                fan_out=int(r["fan_out"]),
                write_count=int(r["write_count"]),
                side_effects=int(r["side_effects"]),
                reader_only=bool(r["reader_only"]),
                score=float(r["score"]),
                evidence_map={f"seam:{prog}": [prog]},
            ))
        # rows already ordered by Cypher; keep stable order
        return out
