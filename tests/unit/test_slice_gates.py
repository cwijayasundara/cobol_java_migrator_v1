import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from cobol_modernizer.persistence.tables import Base, Workspace
from cobol_modernizer.cost.policy import CostPolicy, CostLedger, BudgetExceeded
from cobol_modernizer.slice.gates import (
    record_gate, approve_gate, SLICE_GATE_KEYS, advance_if_approved,
)


def _session():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return Session(eng)


def test_slice_gate_keys_cover_the_journey():
    assert SLICE_GATE_KEYS == [
        "brd_groundedness", "seam", "stories_dag",
        "design_data_ownership", "code", "equivalence",
    ]


def test_record_and_approve_gate_with_rbac_identity():
    s = _session()
    ws = Workspace(name="sample", repo_slug="sample-cobol",
                   created_by="cwijay@biz2bricks.ai")
    s.add(ws); s.flush()
    g = record_gate(s, workspace_id=ws.id, gate_key="brd_groundedness",
                    threshold={"min_weighted": 4.2, "accuracy_floor": 3},
                    result={"weighted": 4.4, "accuracy": 4})
    ap = approve_gate(s, gate_id=g.id, decision="approved",
                      approver_email="lead@biz2bricks.ai",
                      approver_role="lead_engineer", rationale="grounded, scoped")
    s.commit()
    assert g.status == "passed"
    assert ap.approver_email == "lead@biz2bricks.ai"
    assert ap.approver_role == "lead_engineer"


def test_advance_blocked_when_cost_exceeded():
    ledger = CostLedger()
    ledger.set_cap(workspace_id="w1", run_id=None, cap_usd=5.0)
    ledger.set_cap(workspace_id="w1", run_id="r1", cap_usd=5.0)
    policy = CostPolicy(ledger)
    policy.record_usage(workspace_id="w1", run_id="r1", token_usage={}, cost_usd=6.0)
    with pytest.raises(BudgetExceeded):
        advance_if_approved(policy, workspace_id="w1", run_id="r1", gate_passed=True)


def test_advance_blocked_when_gate_not_passed():
    ledger = CostLedger(); ledger.set_cap(workspace_id="w1", run_id=None, cap_usd=5.0)
    ledger.set_cap(workspace_id="w1", run_id="r1", cap_usd=5.0)
    policy = CostPolicy(ledger)
    assert advance_if_approved(policy, workspace_id="w1", run_id="r1",
                               gate_passed=False) is False
