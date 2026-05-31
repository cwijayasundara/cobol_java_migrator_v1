from cobol_modernizer.deploy.routing import RoutingController, RouteTarget
from cobol_modernizer.deploy.rollback import RollbackGuard, CanaryHealth


def _canarying():
    rc = RoutingController(slice_name="s")
    rc.flip(canary_pct=10, deploy_gate_passed=True)
    return rc


def test_healthy_canary_stays():
    rc = _canarying()
    guard = RollbackGuard(rc, workspace_id="w1", slice_name="s",
                          max_error_rate=0.01, max_divergence_rate=0.0)
    ev = guard.observe(CanaryHealth(requests=1000, errors=2, divergences=0))
    assert ev is None
    assert rc.canary_pct == 10


def test_error_rate_breach_rolls_back():
    rc = _canarying()
    guard = RollbackGuard(rc, workspace_id="w1", slice_name="s",
                          max_error_rate=0.01, max_divergence_rate=0.0)
    ev = guard.observe(CanaryHealth(requests=1000, errors=50, divergences=0))
    assert ev is not None
    assert ev.reason == "error_rate"
    assert ev.to_canary_pct == 0
    assert rc.route("anything") is RouteTarget.LEGACY   # rollback proven


def test_equivalence_divergence_breach_rolls_back():
    rc = _canarying()
    guard = RollbackGuard(rc, workspace_id="w1", slice_name="s",
                          max_error_rate=0.05, max_divergence_rate=0.0)
    ev = guard.observe(CanaryHealth(requests=1000, errors=0, divergences=1))
    assert ev is not None
    assert ev.reason == "equivalence_divergence"
    assert rc.canary_pct == 0
