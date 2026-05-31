"""Automated, proven rollback. Deterministic thresholds only — no LLM in the
decision path. A single equivalence divergence (vs the Phase 3 Equivalence Lab
golden master) is enough to roll back in a card domain (max_divergence_rate
defaults to 0.0)."""
from __future__ import annotations

from dataclasses import dataclass
from cobol_modernizer.deploy.models import RollbackEvent
from cobol_modernizer.deploy.routing import RoutingController


@dataclass(frozen=True)
class CanaryHealth:
    requests: int
    errors: int
    divergences: int          # canary-vs-COBOL diffs outside tolerance (Equivalence Lab)

    @property
    def error_rate(self) -> float:
        return self.errors / self.requests if self.requests else 0.0

    @property
    def divergence_rate(self) -> float:
        return self.divergences / self.requests if self.requests else 0.0


class RollbackGuard:
    def __init__(self, routing: RoutingController, *, workspace_id: str,
                 slice_name: str, max_error_rate: float = 0.01,
                 max_divergence_rate: float = 0.0) -> None:
        self.routing = routing
        self.workspace_id = workspace_id
        self.slice_name = slice_name
        self.max_error_rate = max_error_rate
        self.max_divergence_rate = max_divergence_rate

    def observe(self, health: CanaryHealth) -> RollbackEvent | None:
        reason: str | None = None
        if health.divergence_rate > self.max_divergence_rate:
            reason = "equivalence_divergence"
        elif health.error_rate > self.max_error_rate:
            reason = "error_rate"
        if reason is None:
            return None
        from_pct = self.routing.canary_pct
        self.routing.reset_to_legacy(reason=reason)
        return RollbackEvent(
            workspace_id=self.workspace_id, slice_name=self.slice_name,
            reason=reason, from_canary_pct=from_pct, to_canary_pct=0,
            triggered_by="auto",
        )
