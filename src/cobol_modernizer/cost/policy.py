"""Per-workspace AND per-run hard cost caps with a kill-switch.

The pure-Python ``CostLedger`` mirrors the Postgres ``budget`` table so the
policy logic is unit-tested without a DB. In production a DB-backed ledger
implements the same surface. The cap is a HARD ceiling: once spend >= cap the
kill-switch trips and ``check`` raises ``BudgetExceeded`` — callers must stop.
"""
from __future__ import annotations

from typing import Optional

# (workspace_id, run_id-or-None) -> value. run_id=None is the workspace ledger.
_Key = tuple[str, Optional[str]]


class BudgetExceeded(Exception):
    """Raised when a run or its workspace has reached/exceeded its cost cap."""


class CostLedger:
    """In-memory caps + running spend + kill-switch state."""

    def __init__(self) -> None:
        self._cap: dict[_Key, float] = {}
        self._spent: dict[_Key, float] = {}
        self._tokens: dict[_Key, dict[str, int]] = {}
        self._killed: dict[_Key, bool] = {}

    def set_cap(self, *, workspace_id: str, run_id: Optional[str], cap_usd: float) -> None:
        if cap_usd < 0:
            raise ValueError(f"cap_usd must be >= 0, got {cap_usd}")
        self._cap[(workspace_id, run_id)] = cap_usd

    def has_cap(self, key: _Key) -> bool:
        return key in self._cap

    def cap(self, key: _Key) -> float:
        # Fail-closed: an unconfigured cap denies spend (0.0), never allows it
        # (inf). Both the run and workspace caps MUST be set before usage is
        # recorded — a hard ceiling that defaults to "off" is not a ceiling.
        return self._cap.get(key, 0.0)

    def spent(self, key: _Key) -> float:
        return self._spent.get(key, 0.0)

    def add(self, key: _Key, cost_usd: float, token_usage: dict[str, int]) -> None:
        # Clamp non-positive deltas: a kill-switch must be sticky, so spend can
        # only ever increase — a negative cost must not buy back headroom.
        cost_usd = max(0.0, cost_usd)
        self._spent[key] = self._spent.get(key, 0.0) + cost_usd
        bucket = self._tokens.setdefault(
            key, {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0})
        for name, value in (token_usage or {}).items():
            bucket[name] = bucket.get(name, 0) + max(0, value)

    def trip(self, key: _Key) -> None:
        self._killed[key] = True

    def killed(self, key: _Key) -> bool:
        return self._killed.get(key, False)


class CostPolicy:
    """Enforces the run and workspace caps against a ``CostLedger``."""

    def __init__(self, ledger: CostLedger) -> None:
        self._ledger = ledger

    def record_usage(self, *, workspace_id: str, run_id: str,
                     token_usage: dict[str, int], cost_usd: float) -> None:
        """Add a ResultMessage's 4-bucket usage + cost to BOTH the run and
        workspace ledgers."""
        self._ledger.add((workspace_id, run_id), cost_usd, token_usage)
        self._ledger.add((workspace_id, None), cost_usd, token_usage)

    def check(self, *, workspace_id: str, run_id: str) -> None:
        """Raise BudgetExceeded if run.spent >= run.cap OR workspace.spent >=
        workspace.cap. Trips the kill-switch before raising."""
        run_key = (workspace_id, run_id)
        ws_key = (workspace_id, None)
        run_over = self._ledger.spent(run_key) >= self._ledger.cap(run_key)
        ws_over = self._ledger.spent(ws_key) >= self._ledger.cap(ws_key)
        if run_over or ws_over:
            # Trip every scope that breached so the kill-switch reflects reality:
            # a workspace breach must stop sibling runs, not just this one.
            self._ledger.trip(run_key)
            if ws_over:
                self._ledger.trip(ws_key)
            scope = "run" if run_over else "workspace"
            raise BudgetExceeded(
                f"{scope} cap reached for workspace={workspace_id} run={run_id}")

    def is_killed(self, *, workspace_id: str, run_id: str) -> bool:
        # Killed if either this run OR its workspace tripped the switch.
        return (self._ledger.killed((workspace_id, run_id))
                or self._ledger.killed((workspace_id, None)))

    def remaining_usd(self, *, workspace_id: str) -> float:
        ws_key = (workspace_id, None)
        return max(0.0, self._ledger.cap(ws_key) - self._ledger.spent(ws_key))
