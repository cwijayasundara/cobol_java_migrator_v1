from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.persistence.tables import Workspace


router = APIRouter(prefix="/api", tags=["controlplane-backlog"])


def _workspace(session: Session, wid: str) -> Workspace:
    ws = session.get(Workspace, wid)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"workspace {wid} not found")
    return ws


@router.get("/workspaces/{wid}/backlog")
def backlog_status(wid: str, session: Session = Depends(get_session), neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    return {"status": "idle", "result": None, "error": None, "repo_slug": ws.repo_slug}
