"""Deterministic analysis stages wired to the parsed Neo4j graph (no LLM):

- POST /api/workspaces/{id}/seams — ranked strangler-fig seam candidates
  (reader/writer split, blast radius, testability, data-ownership, risk), via the
  seam engine's pure-Cypher scorer.
- POST /api/workspaces/{id}/plan — an acyclic story DAG derived from those seams
  (deterministic dependency derivation + topological order; the LLM INVEST judge
  from the full pipeline is intentionally skipped here).

Both run over the repo's parsed graph; they 409 if the repo hasn't been parsed."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from neo4j.exceptions import DriverError, Neo4jError
from sqlalchemy import select
from sqlalchemy.orm import Session

from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.persistence.tables import JourneyStage, Workspace
from cobol_modernizer.planner.dag import is_acyclic, topo_order
from cobol_modernizer.planner.dependency import derive_dependencies, stories_from_seam_set
from cobol_modernizer.seam.service import rank_candidates

router = APIRouter(prefix="/api", tags=["controlplane-analysis"])
_NEO4J_ERRORS = (Neo4jError, DriverError)


def _workspace(session: Session, wid: str) -> Workspace:
    ws = session.get(Workspace, wid)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"workspace {wid} not found")
    return ws


def _mark_passed(session: Session, wid: str, stage_key: str) -> None:
    for st in session.execute(
        select(JourneyStage).where(JourneyStage.workspace_id == wid,
                                   JourneyStage.stage_key == stage_key)
    ).scalars().all():
        st.status = "passed"


def _ranked(neo4j, repo: str, limit: int = 25) -> list[dict]:
    try:
        return rank_candidates(neo4j, repo=repo, limit=limit)
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")


@router.post("/workspaces/{wid}/seams")
def run_seams(wid: str, session: Session = Depends(get_session),
              neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    cands = _ranked(neo4j, ws.repo_slug)
    if not cands:
        raise HTTPException(status_code=409,
                            detail="no seam candidates — run the Parse stage first")
    _mark_passed(session, wid, "seams")
    session.flush()
    return {"repo_slug": ws.repo_slug, "count": len(cands), "candidates": cands}


@router.post("/workspaces/{wid}/plan")
def run_plan(wid: str, session: Session = Depends(get_session),
             neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    cands = _ranked(neo4j, ws.repo_slug)
    if not cands:
        raise HTTPException(status_code=409,
                            detail="no seams to plan — run the Parse stage first")
    stories = stories_from_seam_set(cands, repo_id=ws.repo_slug)
    dag = derive_dependencies(stories, cands, repo_id=ws.repo_slug)
    acyclic = is_acyclic(dag)
    order = topo_order(dag) if acyclic else []
    _mark_passed(session, wid, "plan")
    session.flush()
    return {
        "repo_slug": ws.repo_slug, "acyclic": acyclic, "topo_order": order,
        "stories": [s.model_dump(mode="json") for s in dag.stories],
    }
