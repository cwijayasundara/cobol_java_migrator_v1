"""CostVerifier — wraps a unit of agent work with the per-run/per-workspace cap.
On a cap crossing it ABORTS the work (no further charges) and emits an
ApprovalRequest for an attributed human decision (master plan §3, §1.6/§1.7)."""
from __future__ import annotations

from dataclasses import dataclass
from cobol_modernizer.cost.policy import CostPolicy, BudgetExceeded

@dataclass(frozen=True)
class ApprovalRequest:
    workspace_id: str
    run_id: str
    scope: str          # 'run' | 'workspace'
    spent_usd: float
    cap_usd: float
    reason: str

class CostVerifier:
    def __init__(self, policy: CostPolicy, *, workspace_id: str, run_id: str) -> None:
        self.policy = policy
        self.workspace_id = workspace_id
        self.run_id = run_id
        self.aborted = False

    def charge(self, *, token_usage: dict[str, int], cost_usd: float):
        """Record usage then enforce the cap. Returns None when under cap;
        returns an ApprovalRequest (and sets self.aborted) on first crossing.
        Subsequent calls raise BudgetExceeded — the run is stoppable-safe."""
        if self.aborted:
            raise BudgetExceeded(
                f"run {self.run_id} already aborted pending approval")
        self.policy.record_usage(workspace_id=self.workspace_id,
                                 run_id=self.run_id,
                                 token_usage=token_usage, cost_usd=cost_usd)
        try:
            self.policy.check(workspace_id=self.workspace_id, run_id=self.run_id)
        except BudgetExceeded as exc:
            self.aborted = True
            run_remaining = self.policy.remaining_usd(workspace_id=self.workspace_id)
            return ApprovalRequest(
                workspace_id=self.workspace_id, run_id=self.run_id,
                scope="run" if self.policy.is_killed(
                    workspace_id=self.workspace_id, run_id=self.run_id) else "workspace",
                spent_usd=cost_usd, cap_usd=run_remaining, reason=str(exc))
        return None
