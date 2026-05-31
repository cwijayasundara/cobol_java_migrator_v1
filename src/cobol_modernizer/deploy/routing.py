"""The routing enabling-point. Weight is data (a percentage), never an
irreversible code change. Increasing canary traffic requires a PASSED deploy
gate; decreasing to legacy is always allowed (making the system safer must
never be blocked). route(key) is a deterministic hash so a given account is
consistently served by one path during a canary."""
from __future__ import annotations

import hashlib
from enum import Enum


class RouteTarget(Enum):
    LEGACY = "legacy"
    CANARY = "canary"


class GateNotPassed(Exception):
    """Raised when raising canary traffic without a passed deploy gate."""


class RoutingController:
    def __init__(self, *, slice_name: str, canary_pct: int = 0) -> None:
        self.slice_name = slice_name
        self._canary_pct = canary_pct

    @property
    def canary_pct(self) -> int:
        return self._canary_pct

    @property
    def legacy_pct(self) -> int:
        return 100 - self._canary_pct

    def flip(self, *, canary_pct: int, deploy_gate_passed: bool) -> None:
        if not 0 <= canary_pct <= 100:
            raise ValueError("canary_pct must be 0..100")
        if canary_pct > self._canary_pct and not deploy_gate_passed:
            raise GateNotPassed(
                f"raising canary to {canary_pct}% requires a passed deploy gate"
            )
        self._canary_pct = canary_pct

    def reset_to_legacy(self, *, reason: str) -> None:
        """Always allowed — getting safer is never gated."""
        self._canary_pct = 0

    def route(self, key: str) -> RouteTarget:
        if self._canary_pct <= 0:
            return RouteTarget.LEGACY
        if self._canary_pct >= 100:
            return RouteTarget.CANARY
        digest = hashlib.sha256(f"{self.slice_name}:{key}".encode()).digest()
        bucket = int.from_bytes(digest[:4], "big") % 100
        return RouteTarget.CANARY if bucket < self._canary_pct else RouteTarget.LEGACY
