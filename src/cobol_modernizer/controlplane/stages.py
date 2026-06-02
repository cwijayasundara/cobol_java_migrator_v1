"""The canonical cockpit journey stages (backend source of truth, mirroring
web/src/lib/stages.ts) and their gate-key mapping."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StageDef:
    key: str
    label: str
    ordinal: int
    gate_key: str | None


JOURNEY_STAGES: list[StageDef] = [
    StageDef("outcome", "Outcome", 0, None),
    StageDef("intake", "Intake", 1, None),
    StageDef("parse", "Parse", 2, "parse"),
    StageDef("graph", "Graph", 3, "graph"),
    StageDef("explore", "Explore", 4, None),
    StageDef("blueprint", "Blueprint", 5, "brd_groundedness"),
    StageDef("backlog", "Backlog", 6, "backlog_coverage"),
    StageDef("seams", "Seams", 7, None),
    StageDef("plan", "Plan", 8, "stories_dag"),
    StageDef("domain", "Domain Design", 9, None),
    StageDef("design", "Design", 10, "design_data_ownership"),
    StageDef("build", "Build", 11, "code"),
    StageDef("verify", "Verify", 12, "equivalence"),
]


def gate_key_for(stage_key: str) -> str | None:
    for s in JOURNEY_STAGES:
        if s.key == stage_key:
            return s.gate_key
    return None
