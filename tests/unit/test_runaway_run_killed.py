import pytest
from cobol_modernizer.cost.policy import CostPolicy, CostLedger, BudgetExceeded
from cobol_modernizer.cost.verifier import CostVerifier, ApprovalRequest

def test_runaway_loop_is_killed_after_cap():
    ledger = CostLedger()
    ledger.set_cap(workspace_id="w1", run_id=None, cap_usd=50.0)
    ledger.set_cap(workspace_id="w1", run_id="runaway", cap_usd=5.0)
    v = CostVerifier(CostPolicy(ledger), workspace_id="w1", run_id="runaway")
    charges, approval = 0, None
    for _ in range(1000):                      # synthetic runaway loop
        req = None
        try:
            req = v.charge(token_usage={"input": 100000}, cost_usd=1.0)
        except BudgetExceeded:
            break                              # already aborted -> stoppable-safe
        charges += 1
        if isinstance(req, ApprovalRequest):
            approval = req
            break
    assert approval is not None
    assert charges <= 6                        # ~5 under $1 each, then killed
    assert v.policy.is_killed(workspace_id="w1", run_id="runaway") is True
