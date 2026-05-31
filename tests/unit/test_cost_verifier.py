import pytest
from cobol_modernizer.cost.policy import CostPolicy, CostLedger, BudgetExceeded
from cobol_modernizer.cost.verifier import CostVerifier, ApprovalRequest

def _policy():
    l = CostLedger()
    l.set_cap(workspace_id="w1", run_id=None, cap_usd=10.0)
    l.set_cap(workspace_id="w1", run_id="r1", cap_usd=2.0)
    return CostPolicy(l)

def test_charge_under_cap_returns_none():
    v = CostVerifier(_policy(), workspace_id="w1", run_id="r1")
    assert v.charge(token_usage={"input": 10}, cost_usd=1.0) is None
    assert v.aborted is False

def test_charge_over_cap_aborts_and_returns_approval_request():
    v = CostVerifier(_policy(), workspace_id="w1", run_id="r1")
    req = v.charge(token_usage={}, cost_usd=2.5)
    assert isinstance(req, ApprovalRequest)
    assert req.scope == "run" and req.workspace_id == "w1" and req.run_id == "r1"
    assert v.aborted is True
    assert v.policy.is_killed(workspace_id="w1", run_id="r1") is True

def test_workspace_breach_reports_workspace_scope():
    l = CostLedger()
    l.set_cap(workspace_id="w1", run_id=None, cap_usd=2.0)
    l.set_cap(workspace_id="w1", run_id="r1", cap_usd=10.0)
    v = CostVerifier(CostPolicy(l), workspace_id="w1", run_id="r1")
    req = v.charge(token_usage={}, cost_usd=2.5)
    assert isinstance(req, ApprovalRequest)
    assert req.scope == "workspace"
    assert v.aborted is True

def test_aborted_verifier_refuses_further_charges():
    v = CostVerifier(_policy(), workspace_id="w1", run_id="r1")
    v.charge(token_usage={}, cost_usd=2.5)
    with pytest.raises(BudgetExceeded):
        v.charge(token_usage={}, cost_usd=0.1)
