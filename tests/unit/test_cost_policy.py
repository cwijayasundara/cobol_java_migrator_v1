import pytest
from cobol_modernizer.cost.policy import CostPolicy, CostLedger, BudgetExceeded


def _ledger():
    l = CostLedger()
    l.set_cap(workspace_id="w1", run_id=None, cap_usd=10.0)
    l.set_cap(workspace_id="w1", run_id="r1", cap_usd=2.0)
    return l


def test_under_cap_ok():
    p = CostPolicy(_ledger())
    p.record_usage(workspace_id="w1", run_id="r1",
                   token_usage={"input":100,"output":50,"cache_read":0,"cache_creation":0},
                   cost_usd=1.0)
    p.check(workspace_id="w1", run_id="r1")  # no raise
    assert p.remaining_usd(workspace_id="w1") == 9.0


def test_run_cap_trips_kill_switch():
    p = CostPolicy(_ledger())
    p.record_usage(workspace_id="w1", run_id="r1", token_usage={}, cost_usd=2.5)
    with pytest.raises(BudgetExceeded):
        p.check(workspace_id="w1", run_id="r1")
    assert p.is_killed(workspace_id="w1", run_id="r1") is True
