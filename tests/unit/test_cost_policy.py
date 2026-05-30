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


def test_missing_cap_fails_closed():
    # No caps configured: any check denies (a hard ceiling defaults to "off"
    # = deny, never allow).
    p = CostPolicy(CostLedger())
    p.record_usage(workspace_id="w1", run_id="r1", token_usage={}, cost_usd=0.0)
    with pytest.raises(BudgetExceeded):
        p.check(workspace_id="w1", run_id="r1")


def test_workspace_cap_trips_sibling_runs():
    l = CostLedger()
    l.set_cap(workspace_id="w1", run_id=None, cap_usd=2.0)
    l.set_cap(workspace_id="w1", run_id="r1", cap_usd=100.0)
    p = CostPolicy(l)
    p.record_usage(workspace_id="w1", run_id="r1", token_usage={}, cost_usd=3.0)
    with pytest.raises(BudgetExceeded):
        p.check(workspace_id="w1", run_id="r1")
    # A different run in the same over-budget workspace is also killed.
    assert p.is_killed(workspace_id="w1", run_id="r2") is True


def test_negative_cost_cannot_buy_back_headroom():
    p = CostPolicy(_ledger())
    p.record_usage(workspace_id="w1", run_id="r1", token_usage={}, cost_usd=2.5)
    # A negative "refund" must not lower spend below the cap.
    p.record_usage(workspace_id="w1", run_id="r1", token_usage={"input": -10},
                   cost_usd=-5.0)
    with pytest.raises(BudgetExceeded):
        p.check(workspace_id="w1", run_id="r1")


def test_set_cap_rejects_negative():
    l = CostLedger()
    with pytest.raises(ValueError):
        l.set_cap(workspace_id="w1", run_id=None, cap_usd=-1.0)
