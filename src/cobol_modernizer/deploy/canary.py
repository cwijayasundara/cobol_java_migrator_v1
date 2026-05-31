"""End-to-end canary lifecycle behind the hard deploy gate + CostPolicy.
Order: smoke -> perf -> (gate?) flip -> observe -> promote|rollback.
No LLM in the decision path; all thresholds are deterministic; rollback is
automatic and proven (route returns to 100% legacy)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from cobol_modernizer.deploy.models import SmokeResult, PerfBaseline, RollbackEvent
from cobol_modernizer.deploy.routing import RoutingController, GateNotPassed
from cobol_modernizer.deploy.rollback import RollbackGuard, CanaryHealth
from cobol_modernizer.cost.policy import CostPolicy, BudgetExceeded


@dataclass
class CanaryDeps:
    routing: RoutingController
    guard: RollbackGuard
    cost: CostPolicy
    smoke: Callable[[], SmokeResult]
    perf: Callable[[], tuple[PerfBaseline, int]]


@dataclass
class CanaryResult:
    status: str                       # promoted|rolled_back|blocked_no_gate|killed
    smoke: SmokeResult | None = None
    perf: PerfBaseline | None = None
    rollback_event: RollbackEvent | None = None
    detail: str = ""


# nominal compute cost per canary phase (budgeted; real costs recorded by callers)
_PHASE_COST_USD = 0.05


class CanaryOrchestrator:
    def __init__(self, deps: CanaryDeps, *, workspace_id: str, run_id: str,
                 slice_name: str) -> None:
        self.deps = deps
        self.workspace_id = workspace_id
        self.run_id = run_id
        self.slice_name = slice_name

    def _spend(self, phase: str) -> None:
        self.deps.cost.record_usage(
            workspace_id=self.workspace_id, run_id=self.run_id,
            token_usage={}, cost_usd=_PHASE_COST_USD)
        self.deps.cost.check(workspace_id=self.workspace_id, run_id=self.run_id)

    def run(self, *, deploy_gate_passed: bool, canary_pct: int,
            max_p95_ratio: float, health: CanaryHealth) -> CanaryResult:
        try:
            self._spend("smoke")
            smoke = self.deps.smoke()
            if not smoke.passed:
                self.deps.routing.reset_to_legacy(reason="smoke_failed")
                return CanaryResult(status="rolled_back", smoke=smoke,
                                    detail="smoke failed; never flipped")

            self._spend("perf")
            perf, divergences = self.deps.perf()
            if divergences > 0 or not perf.meets(max_p95_ratio=max_p95_ratio):
                self.deps.routing.reset_to_legacy(reason="perf_or_divergence")
                return CanaryResult(status="rolled_back", smoke=smoke, perf=perf,
                                    detail="perf/divergence gate failed pre-flip")

            try:
                self.deps.routing.flip(canary_pct=canary_pct,
                                       deploy_gate_passed=deploy_gate_passed)
            except GateNotPassed:
                return CanaryResult(status="blocked_no_gate", smoke=smoke, perf=perf,
                                    detail="deploy gate not passed; flip refused")

            self._spend("observe")
            event = self.deps.guard.observe(health)
            if event is not None:
                return CanaryResult(status="rolled_back", smoke=smoke, perf=perf,
                                    rollback_event=event, detail=event.reason)
            return CanaryResult(status="promoted", smoke=smoke, perf=perf)
        except BudgetExceeded:
            self.deps.routing.reset_to_legacy(reason="budget_killed")
            return CanaryResult(status="killed", detail="cost cap tripped kill-switch")
