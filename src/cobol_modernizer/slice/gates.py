"""Hard human gates for the thin-slice journey, persisted in Postgres gate/approval.
Every approval is attributed (RBAC: approver_email + approver_role + rationale).
Advancing a stage also checks the cost cap (kill-switch) — no stage proceeds past an
unmet gate or an exceeded budget (master plan §1.6, §1.7)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from cobol_modernizer.cost.policy import CostPolicy
from cobol_modernizer.persistence.tables import Approval, Gate

# The six hard gates of the thin-slice journey, in order.
SLICE_GATE_KEYS = [
    "brd_groundedness", "seam", "stories_dag",
    "design_data_ownership", "code", "equivalence",
]


def record_gate(session: Session, *, workspace_id, gate_key: str,
                threshold: dict, result: dict) -> Gate:
    g = Gate(workspace_id=workspace_id, stage_id=None, gate_key=gate_key,
             status="open", threshold=threshold, result=result)
    session.add(g)
    session.flush()
    return g


def approve_gate(session: Session, *, gate_id, decision: str,
                 approver_email: str, approver_role: str, rationale: str,
                 risk_accepted: bool = False) -> Approval:
    if not approver_email or not approver_role:
        raise ValueError("attributed approval requires approver_email and role")
    ap = Approval(gate_id=gate_id, decision=decision,
                  approver_email=approver_email, approver_role=approver_role,
                  risk_accepted=risk_accepted, rationale=rationale)
    session.add(ap)
    g = session.get(Gate, gate_id)
    g.status = "passed" if decision in ("approved", "waived_with_risk") else "failed"
    session.flush()
    return ap


def advance_if_approved(policy: CostPolicy, *, workspace_id: str, run_id: str,
                        gate_passed: bool) -> bool:
    """Advance only if the gate passed AND the budget is intact. Raises
    BudgetExceeded (and trips the kill-switch) if the cap is hit; returns False if
    the gate did not pass."""
    if not gate_passed:
        return False
    policy.check(workspace_id=workspace_id, run_id=run_id)  # raises on cap
    return True
