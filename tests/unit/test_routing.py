import pytest
from cobol_modernizer.deploy.routing import RoutingController, RouteTarget, GateNotPassed


def test_default_is_full_legacy():
    rc = RoutingController(slice_name="account-view-service")
    assert rc.canary_pct == 0
    assert rc.route("ACCT-00000000001") is RouteTarget.LEGACY


def test_flip_requires_passed_deploy_gate():
    rc = RoutingController(slice_name="account-view-service")
    with pytest.raises(GateNotPassed):
        rc.flip(canary_pct=10, deploy_gate_passed=False)
    rc.flip(canary_pct=10, deploy_gate_passed=True)
    assert rc.canary_pct == 10


def test_route_is_deterministic_per_key():
    rc = RoutingController(slice_name="s")
    rc.flip(canary_pct=50, deploy_gate_passed=True)
    a = rc.route("ACCT-42")
    b = rc.route("ACCT-42")
    assert a is b  # same key -> same target every call


def test_canary_share_matches_weight_within_tolerance():
    rc = RoutingController(slice_name="s")
    rc.flip(canary_pct=20, deploy_gate_passed=True)
    keys = [f"ACCT-{i:08d}" for i in range(10000)]
    canary = sum(1 for k in keys if rc.route(k) is RouteTarget.CANARY)
    share = canary / len(keys)
    assert 0.15 <= share <= 0.25   # ~20% within hashing tolerance


def test_reset_to_legacy_is_always_allowed():
    rc = RoutingController(slice_name="s")
    rc.flip(canary_pct=100, deploy_gate_passed=True)
    rc.reset_to_legacy(reason="rollback")   # no gate needed to make SAFER
    assert rc.canary_pct == 0
    assert rc.route("anything") is RouteTarget.LEGACY
