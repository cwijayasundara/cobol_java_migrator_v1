"""Phase-6 deployment/canary typed contracts. All json_schema-safe (plain
scalars/lists), so any LLM-facing summary can serialize them — though the
routing/rollback decision path uses ZERO LLM."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, model_validator


class DeploySpec(BaseModel):
    workspace_id: str
    artifact_id: str                 # artifact.id of the spring_boot_project
    slice_name: str                  # e.g. "account-view-service"
    image_ref: str                   # tag, e.g. "account-view-service:abc123"
    image_digest: str                # "sha256:..." — reproducibility anchor


class SmokeResult(BaseModel):
    slice_name: str
    health_ok: bool
    endpoints_ok: int
    endpoints_total: int
    failures: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.health_ok and self.endpoints_ok == self.endpoints_total


class PerfBaseline(BaseModel):
    slice_name: str
    cobol_p95_ms: float
    canary_p95_ms: float
    cobol_throughput_rps: float
    canary_throughput_rps: float
    fixtures: int

    @property
    def p95_ratio(self) -> float:
        if self.cobol_p95_ms <= 0:
            return float("inf")
        return round(self.canary_p95_ms / self.cobol_p95_ms, 4)

    def meets(self, *, max_p95_ratio: float) -> bool:
        return self.p95_ratio <= max_p95_ratio


class RolloutPlan(BaseModel):
    canary_pct: int = Field(ge=0, le=100)
    legacy_pct: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _sum_100(self) -> "RolloutPlan":
        if self.canary_pct + self.legacy_pct != 100:
            raise ValueError("canary_pct + legacy_pct must equal 100")
        return self

    def is_full_legacy(self) -> bool:
        return self.canary_pct == 0


class RollbackEvent(BaseModel):
    workspace_id: str
    slice_name: str
    reason: str                      # error_rate | equivalence_divergence | smoke_failed | human
    from_canary_pct: int
    to_canary_pct: int
    triggered_by: Literal["auto", "human"]


class FitnessCheckResult(BaseModel):
    key: str
    passed: bool
    measured: float
    threshold: float
    direction: Literal["max", "min"]   # "max": measured<=threshold ok; "min": measured>=threshold ok


class FitnessReport(BaseModel):
    workspace_id: str
    commit_sha: str
    checks: list[FitnessCheckResult] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def regressions(self, prior: "FitnessReport | None") -> list[str]:
        if prior is None:
            return [c.key for c in self.checks if not c.passed]
        prior_by_key = {c.key: c for c in prior.checks}
        out: list[str] = []
        for c in self.checks:
            p = prior_by_key.get(c.key)
            if p is not None and p.passed and not c.passed:
                out.append(c.key)
        return out
