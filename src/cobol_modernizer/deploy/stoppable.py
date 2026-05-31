"""Stoppable-safe invariant: at ANY commit the migration must be recoverable to
100% legacy without data loss. Enforced in CI so no commit can leave the canary
in an unrecoverable state."""
from __future__ import annotations

from dataclasses import dataclass


class NotStoppableSafe(Exception):
    """Raised when a route snapshot cannot be safely rolled back to legacy."""


@dataclass(frozen=True)
class RouteSnapshot:
    canary_pct: int
    legacy_path_available: bool
    deploy_gate_passed: bool


def assert_stoppable_safe(snap: RouteSnapshot) -> None:
    if snap.canary_pct == 0:
        return  # full legacy is always safe
    if not snap.deploy_gate_passed:
        raise NotStoppableSafe(
            "canary traffic served without a passed deploy gate")
    if not snap.legacy_path_available:
        raise NotStoppableSafe(
            "legacy path removed while canary route still active — "
            "no rollback target")
