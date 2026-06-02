"""Blueprint (BRD) stage — grounded LLM Business Requirements Document.

POST /api/workspaces/{id}/blueprint runs the graph-navigated BRD pipeline
(subsystem map-reduce draft → judge → retry-until-high) over the workspace's
parsed Neo4j graph, persists a versioned :BRD node + self-contained HTML, and
marks the `blueprint` stage passed. This is the one analysis stage that calls
Claude, so it needs ANTHROPIC_API_KEY and is slower than the deterministic stages.

GET /api/workspaces/{id}/blueprint/html serves the latest rendered BRD HTML for
inline viewing in the cockpit.

The BRD storage layer keys off a :Repository {slug} node (from the standalone
RepoManager flow), which the cockpit's parse→graph step doesn't create, so we
MERGE one (pointing at the on-disk source dir) before running."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from neo4j.exceptions import DriverError, Neo4jError
from sqlalchemy import select
from sqlalchemy.orm import Session

from pydantic import BaseModel

from cobol_modernizer.brd.pipeline import generate_brd_graph_sync, improve_brd_graph_sync
from cobol_modernizer.brd.storage import BRDStorage
from cobol_modernizer.controlplane import jobs
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.persistence.tables import JourneyStage, Workspace

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["controlplane-blueprint"])
_NEO4J_ERRORS = (Neo4jError, DriverError)

_COUNT_ENTITIES = "MATCH (n:CodeEntity {repo:$repo}) RETURN count(n) AS c"


def _source_root() -> Path:
    return Path(os.environ.get("COBOL_SOURCE_ROOT", "source_code_to_analyse"))


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


def _precheck(neo4j, workspace: Workspace, source_root: Path) -> Path:
    """Fast, synchronous validation run BEFORE queueing the multi-minute job, so the
    UI gets immediate 404/409 feedback instead of polling a doomed run. Returns the
    repo dir. Raises HTTPException on a missing dir or an unparsed graph."""
    slug = workspace.repo_slug
    repo_dir = source_root / slug
    if not repo_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"repo directory '{slug}' not found under {source_root}")
    entities = neo4j.run(_COUNT_ENTITIES, repo=slug)[0]["c"]
    if not entities:
        raise HTTPException(
            status_code=409,
            detail=f"'{slug}' has no parsed graph — run the Parse stage first.")
    return repo_dir


def run_blueprint(*, session: Session, neo4j, workspace: Workspace,
                  source_root: Path,
                  generate: Callable[..., Any] | None = None) -> dict[str, Any]:
    """Generate + persist a BRD for the workspace's repo. `generate` defaults to
    the real graph BRD pipeline (resolved here so tests can inject a stub)."""
    slug = workspace.repo_slug
    repo_dir = _precheck(neo4j, workspace, source_root)
    entities = neo4j.run(_COUNT_ENTITIES, repo=slug)[0]["c"]
    # Storage keys off a :Repository node — ensure one exists for this slug.
    neo4j.run("MERGE (r:Repository {slug: $slug}) "
              "SET r.local_path = $lp, r.name = coalesce(r.name, $slug)",
              slug=slug, lp=str(repo_dir.resolve()))

    logger.info("blueprint: generating BRD for repo=%s (%d graph entities) — "
                "this is a multi-minute LLM run", slug, entities)
    gen = generate or generate_brd_graph_sync
    result = gen(slug, client=neo4j, repo_path=str(repo_dir.resolve()))

    _mark_passed(session, workspace.id, "blueprint")
    session.flush()
    return {
        "repo_slug": slug,
        "brd_id": result.brd_id,
        "version": result.version,
        "rating": result.rating.value if hasattr(result.rating, "value") else result.rating,
        "weighted_score": result.weighted_score,
        "attempts": result.attempts,
        "model": result.model,
        "strategy": result.strategy.value if hasattr(result.strategy, "value") else result.strategy,
        "token_usage": dict(result.token_usage),
    }


class _ImproveBody(BaseModel):
    instruction: str


def _job_view(job: dict) -> dict:
    return {"status": job["status"], "result": job.get("result"),
            "error": job.get("error"), "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at")}


@router.post("/workspaces/{wid}/blueprint", status_code=202)
def blueprint_workspace(wid: str, session: Session = Depends(get_session),
                        neo4j=Depends(get_neo4j)) -> dict:
    """Kick off the (multi-minute) BRD run as a background job and return 202
    immediately; the UI polls GET .../blueprint for status. Validates fast first so
    a missing key / unparsed graph is reported now, not after a long poll."""
    ws = _workspace(session, wid)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=503,
                            detail="ANTHROPIC_API_KEY not set — Blueprint needs an LLM.")
    try:
        _precheck(neo4j, ws, _source_root())
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")

    def _job() -> dict:
        s = jobs.make_session()
        neo = jobs.make_neo4j()
        try:
            ws2 = s.get(Workspace, wid)
            result = run_blueprint(session=s, neo4j=neo, workspace=ws2,
                                   source_root=_source_root())
            s.commit()
            return result
        finally:
            s.close()
            try:
                neo.close()
            except Exception:  # noqa: BLE001
                pass

    logger.info("blueprint: queued background run for workspace=%s repo=%s",
                wid, ws.repo_slug)
    return _job_view(jobs.runner.start("blueprint", wid, _job))


@router.get("/workspaces/{wid}/blueprint")
def blueprint_status(wid: str, session: Session = Depends(get_session),
                     neo4j=Depends(get_neo4j)) -> dict:
    """Poll the background BRD job. After a restart (no in-process job) report a
    previously-persisted BRD as 'done', else 'idle'."""
    ws = _workspace(session, wid)
    job = jobs.runner.get("blueprint", wid)
    if job is not None:
        return _job_view(job)
    try:
        latest = BRDStorage(neo4j).get_latest(ws.repo_slug)
    except _NEO4J_ERRORS:
        latest = None
    if latest:
        return {"status": "done", "error": None, "started_at": None,
                "finished_at": None,
                "result": {"repo_slug": ws.repo_slug, "brd_id": latest.get("id"),
                           "version": latest.get("version"),
                           "rating": latest.get("rating")}}
    return {"status": "idle", "result": None, "error": None,
            "started_at": None, "finished_at": None}


@router.get("/workspaces/{wid}/blueprint/html", response_class=HTMLResponse)
def blueprint_html(wid: str, session: Session = Depends(get_session),
                   neo4j=Depends(get_neo4j)) -> HTMLResponse:
    ws = _workspace(session, wid)
    try:
        latest = BRDStorage(neo4j).get_latest(ws.repo_slug)
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")
    if not latest or not latest.get("html"):
        raise HTTPException(status_code=404,
                            detail="no BRD yet — run the Blueprint stage first")
    return HTMLResponse(content=latest["html"])


@router.post("/workspaces/{wid}/blueprint/improve", status_code=202)
def blueprint_improve(wid: str, body: _ImproveBody,
                      session: Session = Depends(get_session),
                      neo4j=Depends(get_neo4j)) -> dict:
    """Refine the latest BRD per a free-text instruction (graph-grounded) as a
    background job, saving a new version. Validates fast: needs the key, a non-empty
    instruction, and an existing BRD."""
    ws = _workspace(session, wid)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=503,
                            detail="ANTHROPIC_API_KEY not set — Improve needs an LLM.")
    instruction = (body.instruction or "").strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction must be non-empty")
    try:
        if BRDStorage(neo4j).get_latest(ws.repo_slug) is None:
            raise HTTPException(status_code=409,
                                detail="no BRD yet — generate a blueprint first")
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")

    slug = ws.repo_slug
    repo_dir = _source_root() / slug

    def _job() -> dict:
        neo = jobs.make_neo4j()
        try:
            result = improve_brd_graph_sync(slug, instruction, client=neo,
                                            repo_path=str(repo_dir.resolve()))
            return {"repo_slug": slug, "brd_id": result.brd_id,
                    "version": result.version,
                    "rating": result.rating.value if hasattr(result.rating, "value") else result.rating,
                    "weighted_score": result.weighted_score, "model": result.model,
                    "token_usage": dict(result.token_usage)}
        finally:
            try:
                neo.close()
            except Exception:  # noqa: BLE001
                pass

    return _job_view(jobs.runner.start("blueprint-improve", wid, _job))


@router.get("/workspaces/{wid}/blueprint/improve")
def blueprint_improve_status(wid: str, session: Session = Depends(get_session),
                             neo4j=Depends(get_neo4j)) -> dict:
    _workspace(session, wid)
    return _job_view(jobs.runner.get("blueprint-improve", wid))
