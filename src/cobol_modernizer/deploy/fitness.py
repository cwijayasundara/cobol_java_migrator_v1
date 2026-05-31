"""Evolutionary-architecture fitness functions tracking target-state progress.
Deterministic; run on every commit by CI and persisted as a fitness_check row.
'direction'='max' means measured must be <= threshold; 'min' means >="""
from __future__ import annotations

from dataclasses import dataclass
from cobol_modernizer.deploy.models import FitnessReport, FitnessCheckResult


@dataclass(frozen=True)
class Target:
    key: str
    threshold: float
    direction: str   # "max" | "min"

    def check(self, measured: float) -> bool:
        if self.direction == "max":
            return measured <= self.threshold
        return measured >= self.threshold


def load_targets(raw: dict) -> list[Target]:
    return [
        Target(key=k, threshold=float(v["threshold"]), direction=v["direction"])
        for k, v in raw.items()
    ]


def run_fitness(*, workspace_id: str, commit_sha: str,
                measured: dict[str, float], targets: list[Target]) -> FitnessReport:
    checks: list[FitnessCheckResult] = []
    for t in targets:
        m = float(measured[t.key])
        checks.append(FitnessCheckResult(
            key=t.key, passed=t.check(m), measured=m,
            threshold=t.threshold, direction=t.direction,
        ))
    return FitnessReport(workspace_id=workspace_id, commit_sha=commit_sha, checks=checks)
