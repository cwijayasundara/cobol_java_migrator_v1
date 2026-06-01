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

import os
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from neo4j.exceptions import DriverError, Neo4jError
from sqlalchemy import select
from sqlalchemy.orm import Session

from cobol_modernizer.brd.pipeline import generate_brd_graph_sync
from cobol_modernizer.brd.storage import BRDStorage
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.persistence.tables import JourneyStage, Workspace

router = APIRouter(prefix="/api", tags=["controlplane-blueprint"])
_NEO4J_ERRORS = (Neo4jError, DriverError)


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


def run_blueprint(*, session: Session, neo4j, workspace: Workspace,
                  source_root: Path,
                  generate: Callable[..., Any] | None = None) -> dict[str, Any]:
    """Generate + persist a BRD for the workspace's repo. `generate` defaults to
    the real graph BRD pipeline (resolved here so tests can inject a stub)."""
    slug = workspace.repo_slug
    repo_dir = source_root / slug
    if not repo_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"repo directory '{slug}' not found under {source_root}")
    # Storage keys off a :Repository node — ensure one exists for this slug.
    neo4j.run("MERGE (r:Repository {slug: $slug}) "
              "SET r.local_path = $lp, r.name = coalesce(r.name, $slug)",
              slug=slug, lp=str(repo_dir.resolve()))

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


@router.post("/workspaces/{wid}/blueprint")
def blueprint_workspace(wid: str, session: Session = Depends(get_session),
                        neo4j=Depends(get_neo4j)) -> dict:
    """Sync (not async): the BRD pipeline owns its own event loop via asyncio.run,
    so FastAPI must run this in its threadpool. Slow — it makes several LLM calls."""
    ws = _workspace(session, wid)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=503,
                            detail="ANTHROPIC_API_KEY not set — Blueprint needs an LLM.")
    try:
        return run_blueprint(session=session, neo4j=neo4j, workspace=ws,
                             source_root=_source_root())
    except HTTPException:
        raise
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


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
