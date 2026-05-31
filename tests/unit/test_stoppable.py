import pytest
from cobol_modernizer.deploy.stoppable import (
    RouteSnapshot, assert_stoppable_safe, NotStoppableSafe,
)


def test_full_legacy_is_safe():
    assert_stoppable_safe(RouteSnapshot(
        canary_pct=0, legacy_path_available=True, deploy_gate_passed=False))


def test_gated_canary_is_safe():
    assert_stoppable_safe(RouteSnapshot(
        canary_pct=10, legacy_path_available=True, deploy_gate_passed=True))


def test_canary_without_gate_is_unsafe():
    with pytest.raises(NotStoppableSafe, match="gate"):
        assert_stoppable_safe(RouteSnapshot(
            canary_pct=10, legacy_path_available=True, deploy_gate_passed=False))


def test_canary_with_legacy_removed_is_unsafe():
    with pytest.raises(NotStoppableSafe, match="legacy"):
        assert_stoppable_safe(RouteSnapshot(
            canary_pct=10, legacy_path_available=False, deploy_gate_passed=True))


def test_full_canary_with_legacy_gone_is_unsafe_until_retired():
    # cutover (100% canary) is only stoppable-safe once the slice is formally
    # retired AND legacy still reachable for emergency rollback
    with pytest.raises(NotStoppableSafe):
        assert_stoppable_safe(RouteSnapshot(
            canary_pct=100, legacy_path_available=False, deploy_gate_passed=True))
