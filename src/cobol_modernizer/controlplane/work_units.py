"""Workspace work-unit progress endpoints.

The ledger is the shared progress/cache substrate for long stages. This router is
read-only: stage runners write work units via PgRepo, while the cockpit reads this
view to render unit-level progress independent of any particular stage endpoint.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from cobol_modernizer.controlplane.deps import get_session
from cobol_modernizer.persistence.repo import PgRepo
from cobol_modernizer.persistence.tables import Workspace, WorkUnit

router = APIRouter(prefix="/api", tags=["controlplane-work-units"])


def _workspace(session: Session, wid: str) -> Workspace:
    ws = session.get(Workspace, wid)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"workspace {wid} not found")
    return ws


def work_unit_dto(unit: WorkUnit) -> dict:
    return {
        "id": unit.id,
        "workspace_id": unit.workspace_id,
        "agent_run_id": unit.agent_run_id,
        "artifact_id": unit.artifact_id,
        "repo_slug": unit.repo_slug,
        "stage": unit.stage,
        "unit_type": unit.unit_type,
        "unit_key": unit.unit_key,
        "input_hash": unit.input_hash,
        "status": unit.status,
        "attempt": unit.attempt,
        "model": unit.model,
        "timeout_s": float(unit.timeout_s) if unit.timeout_s is not None else None,
        "max_turns": unit.max_turns,
        "token_usage": unit.token_usage,
        "cost_usd": float(unit.cost_usd or 0),
        "started_at": unit.started_at.isoformat() if unit.started_at else None,
        "finished_at": unit.finished_at.isoformat() if unit.finished_at else None,
        "error_cause": unit.error_cause,
        "parent_unit_ids": unit.parent_unit_ids,
    }


@router.get("/workspaces/{wid}/work-units")
def list_work_units(wid: str, stage: str | None = None,
                    status: str | None = None,
                    s: Session = Depends(get_session)) -> dict:
    _workspace(s, wid)
    units = PgRepo(s).list_work_units(workspace_id=wid, stage=stage, status=status)
    counts: dict[str, int] = {}
    by_stage: dict[str, dict[str, int]] = {}
    for unit in units:
        counts[unit.status] = counts.get(unit.status, 0) + 1
        stage_counts = by_stage.setdefault(unit.stage, {})
        stage_counts[unit.status] = stage_counts.get(unit.status, 0) + 1
    return {
        "workspace_id": wid,
        "stage": stage,
        "status": status,
        "total": len(units),
        "counts": counts,
        "by_stage": by_stage,
        "units": [work_unit_dto(u) for u in units],
    }
