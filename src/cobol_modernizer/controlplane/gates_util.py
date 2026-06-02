"""Create-or-update a Gate row keyed by (workspace_id, gate_key), used by the
generation stages to publish a deterministic gate verdict. A gate the user has
explicitly resolved (passed/failed/waived via the approval route) is never silently
flipped back to open by a re-run — only its `result` payload refreshes."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cobol_modernizer.persistence.tables import Gate, JourneyStage, _now

# A gate explicitly resolved by a human (via the approval route) is immutable here.
_HUMAN_RESOLVED = frozenset({"passed", "failed", "waived"})

# NOTE: assumes single-job-per-workspace use; there is no concurrent-insert guard
# (no SELECT ... FOR UPDATE / retry). Out of scope here.


def _stage_id(session: Session, workspace_id: str, stage_key: str) -> str | None:
    row = session.execute(
        select(JourneyStage).where(JourneyStage.workspace_id == workspace_id,
                                   JourneyStage.stage_key == stage_key)
    ).scalars().first()
    return row.id if row else None


def upsert_gate(session: Session, workspace_id: str, stage_key: str, gate_key: str,
                *, passed: bool, result: dict[str, Any], threshold: dict[str, Any]) -> Gate:
    gate = session.execute(
        select(Gate).where(Gate.workspace_id == workspace_id, Gate.gate_key == gate_key)
    ).scalars().first()
    # "open" = blocking / not yet human-resolved (not "failed")
    computed = "passed" if passed else "open"
    if gate is None:
        gate = Gate(workspace_id=workspace_id, stage_id=_stage_id(session, workspace_id, stage_key),
                    gate_key=gate_key, status=computed, threshold=threshold, result=result)
        session.add(gate)
        return gate
    gate.result = result
    gate.threshold = threshold
    gate.updated_at = _now()
    if gate.status not in _HUMAN_RESOLVED:
        gate.status = computed
    return gate
