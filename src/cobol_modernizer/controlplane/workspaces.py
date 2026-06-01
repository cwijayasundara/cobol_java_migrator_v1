"""DB-backed cockpit control-plane routes: workspaces, stages, gates, artifacts,
runs, budget, and the attributed gate-approval transition."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from cobol_modernizer.controlplane.deps import get_session
from cobol_modernizer.controlplane.serializers import (
    approval_dto, artifact_dto, budget_dto, gate_dto, run_dto, stage_dto, workspace_dto,
)
from cobol_modernizer.controlplane.stages import JOURNEY_STAGES
from cobol_modernizer.cost.tiering import resolve_model
from cobol_modernizer.persistence.tables import (
    AgentRun, Approval, Artifact, Budget, Gate, JourneyStage, Workspace,
)

router = APIRouter(prefix="/api", tags=["controlplane"])

_DECISION_TO_GATE = {
    "approved": "passed", "rejected": "failed", "waived_with_risk": "waived",
}


class CreateWorkspaceBody(BaseModel):
    name: str
    repo_slug: str
    created_by: str


class StartRunBody(BaseModel):
    stage_key: str
    role: str
    started_by: str


class ApprovalBody(BaseModel):
    decision: str
    approver_email: str
    approver_role: str
    risk_accepted: bool = False
    rationale: str


def _get_ws(s: Session, wid: str) -> Workspace:
    ws = s.get(Workspace, wid)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"workspace {wid} not found")
    return ws


@router.get("/workspaces")
def list_workspaces(s: Session = Depends(get_session)) -> list[dict]:
    rows = s.execute(select(Workspace).order_by(Workspace.created_at)).scalars().all()
    return [workspace_dto(w) for w in rows]


@router.get("/workspaces/{wid}")
def get_workspace(wid: str, s: Session = Depends(get_session)) -> dict:
    return workspace_dto(_get_ws(s, wid))


@router.post("/workspaces")
def create_workspace(body: CreateWorkspaceBody, s: Session = Depends(get_session)) -> dict:
    # Idempotent per repo: one workspace per repo_slug. Re-creating an existing
    # repo's workspace returns it (no duplicate, no re-seed) so the Portfolio picker
    # can't spawn two cards for the same repo.
    existing = s.execute(
        select(Workspace).where(Workspace.repo_slug == body.repo_slug)
    ).scalars().first()
    if existing is not None:
        return workspace_dto(existing)
    ws = Workspace(name=body.name, repo_slug=body.repo_slug, created_by=body.created_by)
    s.add(ws); s.flush()
    for st in JOURNEY_STAGES:
        s.add(JourneyStage(workspace_id=ws.id, stage_key=st.key, ordinal=st.ordinal,
                           status="running" if st.ordinal == 0 else "pending"))
    s.add(Budget(workspace_id=ws.id, scope="workspace", agent_run_id=None,
                 cap_usd=50, spent_usd=0, killed=False))
    s.flush()
    return workspace_dto(ws)


@router.get("/workspaces/{wid}/stages")
def list_stages(wid: str, s: Session = Depends(get_session)) -> list[dict]:
    _get_ws(s, wid)
    rows = s.execute(select(JourneyStage).where(JourneyStage.workspace_id == wid)
                     .order_by(JourneyStage.ordinal)).scalars().all()
    return [stage_dto(x) for x in rows]


@router.get("/workspaces/{wid}/gates")
def list_gates(wid: str, s: Session = Depends(get_session)) -> list[dict]:
    _get_ws(s, wid)
    rows = s.execute(select(Gate).where(Gate.workspace_id == wid)).scalars().all()
    return [gate_dto(x) for x in rows]


@router.get("/workspaces/{wid}/artifacts")
def list_artifacts(wid: str, s: Session = Depends(get_session)) -> list[dict]:
    _get_ws(s, wid)
    rows = s.execute(select(Artifact).where(Artifact.workspace_id == wid)
                     .order_by(Artifact.created_at.desc())).scalars().all()
    return [artifact_dto(x) for x in rows]


@router.get("/workspaces/{wid}/artifacts/{aid}")
def get_artifact(wid: str, aid: str, s: Session = Depends(get_session)) -> dict:
    art = s.get(Artifact, aid)
    if art is None or art.workspace_id != wid:
        raise HTTPException(status_code=404, detail=f"artifact {aid} not found")
    return artifact_dto(art)


@router.get("/workspaces/{wid}/runs")
def list_runs(wid: str, s: Session = Depends(get_session)) -> list[dict]:
    _get_ws(s, wid)
    rows = s.execute(select(AgentRun).where(AgentRun.workspace_id == wid)
                     .order_by(AgentRun.started_at.desc())).scalars().all()
    return [run_dto(x) for x in rows]


@router.post("/workspaces/{wid}/runs")
def start_run(wid: str, body: StartRunBody, s: Session = Depends(get_session)) -> dict:
    _get_ws(s, wid)
    stage = s.execute(select(JourneyStage).where(
        JourneyStage.workspace_id == wid,
        JourneyStage.stage_key == body.stage_key)).scalars().first()
    run = AgentRun(workspace_id=wid, stage_id=stage.id if stage else None,
                   role=body.role, model=resolve_model(body.role), status="running",
                   started_by=body.started_by, input_tokens=0, output_tokens=0,
                   cache_read_tokens=0, cache_creation_tokens=0, total_cost_usd=0)
    s.add(run); s.flush()
    return run_dto(run)


@router.get("/workspaces/{wid}/budget")
def get_budget(wid: str, s: Session = Depends(get_session)) -> dict:
    _get_ws(s, wid)
    b = s.execute(select(Budget).where(Budget.workspace_id == wid,
                                        Budget.scope == "workspace")).scalars().first()
    if b is None:
        raise HTTPException(status_code=404, detail="no workspace budget")
    return budget_dto(b)


@router.post("/gates/{gate_id}/approval")
def submit_approval(gate_id: str, body: ApprovalBody,
                    s: Session = Depends(get_session)) -> dict:
    gate = s.get(Gate, gate_id)
    if gate is None:
        raise HTTPException(status_code=404, detail=f"gate {gate_id} not found")
    if body.decision not in _DECISION_TO_GATE:
        raise HTTPException(status_code=400, detail=f"bad decision {body.decision}")
    if body.decision == "waived_with_risk" and not body.risk_accepted:
        raise HTTPException(status_code=400, detail="waive requires risk_accepted")
    ap = Approval(gate_id=gate_id, decision=body.decision,
                  approver_email=body.approver_email, approver_role=body.approver_role,
                  risk_accepted=body.risk_accepted, rationale=body.rationale,
                  decided_at=datetime.now(timezone.utc))
    s.add(ap)
    gate.status = _DECISION_TO_GATE[body.decision]
    s.flush()
    return approval_dto(ap)
