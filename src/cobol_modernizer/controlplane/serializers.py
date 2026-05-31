"""Pure ORM-instance -> dict serializers producing JSON identical to the cockpit
DTOs in web/src/lib/types.ts. No DB or HTTP here. Numeric->float, datetime->ISO,
JSON columns passthrough."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from cobol_modernizer.persistence.tables import (
    AgentRun, Approval, Artifact, Budget, Gate, JourneyStage, Workspace,
)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _f(v: Decimal | float | int | None) -> float | None:
    return float(v) if v is not None else None


def workspace_dto(ws: Workspace) -> dict[str, Any]:
    return {
        "id": ws.id, "name": ws.name, "repo_slug": ws.repo_slug,
        "graph_snapshot": ws.graph_snapshot, "created_by": ws.created_by,
        "created_at": _iso(ws.created_at), "status": ws.status,
    }


def stage_dto(s: JourneyStage) -> dict[str, Any]:
    return {
        "id": s.id, "workspace_id": s.workspace_id, "stage_key": s.stage_key,
        "ordinal": s.ordinal, "status": s.status, "updated_at": _iso(s.updated_at),
    }


def run_dto(r: AgentRun) -> dict[str, Any]:
    return {
        "id": r.id, "workspace_id": r.workspace_id, "stage_id": r.stage_id,
        "role": r.role, "model": r.model, "status": r.status,
        "started_by": r.started_by, "started_at": _iso(r.started_at),
        "finished_at": _iso(r.finished_at), "input_tokens": r.input_tokens,
        "output_tokens": r.output_tokens, "cache_read_tokens": r.cache_read_tokens,
        "cache_creation_tokens": r.cache_creation_tokens,
        "total_cost_usd": _f(r.total_cost_usd), "error": r.error,
    }


def artifact_dto(a: Artifact) -> dict[str, Any]:
    return {
        "id": a.id, "workspace_id": a.workspace_id, "stage_id": a.stage_id,
        "agent_run_id": a.agent_run_id, "kind": a.kind, "version": a.version,
        "object_uri": a.object_uri, "content_hash": a.content_hash,
        "evidence_map": a.evidence_map or {}, "created_at": _iso(a.created_at),
    }


def gate_dto(g: Gate) -> dict[str, Any]:
    return {
        "id": g.id, "workspace_id": g.workspace_id, "stage_id": g.stage_id,
        "gate_key": g.gate_key, "status": g.status, "threshold": g.threshold or {},
        "result": g.result or {}, "updated_at": _iso(g.updated_at),
    }


def approval_dto(ap: Approval) -> dict[str, Any]:
    return {
        "id": ap.id, "gate_id": ap.gate_id, "decision": ap.decision,
        "approver_email": ap.approver_email, "approver_role": ap.approver_role,
        "risk_accepted": ap.risk_accepted, "rationale": ap.rationale,
        "decided_at": _iso(ap.decided_at),
    }


def budget_dto(b: Budget) -> dict[str, Any]:
    return {
        "id": b.id, "workspace_id": b.workspace_id, "scope": b.scope,
        "agent_run_id": b.agent_run_id, "cap_usd": _f(b.cap_usd),
        "spent_usd": _f(b.spent_usd), "killed": b.killed, "updated_at": _iso(b.updated_at),
    }
