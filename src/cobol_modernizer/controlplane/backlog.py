"""Backlog stage — graph-grounded BRD → business epics/user stories with acceptance
criteria, a seam/data dependency DAG, and a BRD logic-coverage report. Mirrors
blueprint.py: fast precheck, multi-minute LLM run on the JobRunner, persist a
versioned :Backlog node, upsert the backlog_coverage + brd_logic_coverage gates."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from neo4j.exceptions import DriverError, Neo4jError
from sqlalchemy.orm import Session

from cobol_modernizer.agent.harness import SdkAgentRunner
from cobol_modernizer.backlog.dependency import derive_story_dependencies
from cobol_modernizer.backlog.generator import generate_backlog_payload, parse_backlog_payload
from cobol_modernizer.backlog.render import render_html
from cobol_modernizer.backlog.storage import BacklogStorage
from cobol_modernizer.brd.storage import BRDStorage
from cobol_modernizer.controlplane import jobs
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.controlplane.gates_util import upsert_gate
from cobol_modernizer.persistence.tables import Workspace
from cobol_modernizer.seam.service import rank_candidates
from cobol_modernizer.traceability.coverage import brd_logic_coverage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["controlplane-backlog"])
_NEO4J_ERRORS = (Neo4jError, DriverError)

_GRAPH_REFS_Q = "MATCH (n:CodeEntity {repo:$repo}) RETURN n.qualified_name AS q"
_DEFAULT_MODEL = "claude-sonnet-4-6"


def _coverage_min() -> float:
    try:
        return float(os.environ.get("BACKLOG_COVERAGE_MIN", "0.8"))
    except ValueError:
        return 0.8


def _workspace(session: Session, wid: str) -> Workspace:
    ws = session.get(Workspace, wid)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"workspace {wid} not found")
    return ws


def _job_view(job: dict | None) -> dict:
    if job is None:
        return {"status": "idle", "result": None, "error": None,
                "started_at": None, "finished_at": None}
    return {"status": job["status"], "result": job.get("result"),
            "error": job.get("error"), "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at")}


def _requirement_ids(sections: list[dict]) -> set[str]:
    ids: set[str] = set()
    for sec in sections:
        for req in sec.get("requirements", []) if isinstance(sec, dict) else []:
            rid = req.get("id") if isinstance(req, dict) else None
            if rid:
                ids.add(str(rid))
    return ids


def run_backlog(*, session: Session, neo4j, workspace: Workspace,
                generate: Callable[..., Any] | None = None) -> dict:
    """Generate + persist a backlog and publish its gates. `generate` defaults to the
    real LLM call (injected by tests)."""
    slug = workspace.repo_slug
    brd = BRDStorage(neo4j).get_latest(slug)
    if not brd:
        raise HTTPException(status_code=409, detail=f"no BRD for '{slug}' — run Blueprint first")
    raw_sections = brd.get("sections")
    if isinstance(raw_sections, str):
        try:
            sections = json.loads(raw_sections or "[]")
        except json.JSONDecodeError:
            logger.warning("backlog: malformed BRD sections JSON for %s — treating as empty", slug)
            sections = []
    else:
        sections = raw_sections or []
    known_refs = [r["q"] for r in neo4j.run(_GRAPH_REFS_Q, repo=slug) if r.get("q")]
    known_req_ids = _requirement_ids(sections)

    # Ensure a :Repository node exists for BacklogStorage (mirrors blueprint.py MERGE).
    neo4j.run("MERGE (r:Repository {slug: $slug}) SET r.name = coalesce(r.name, $slug)",
              slug=slug)

    gen = generate or generate_backlog_payload
    raw = asyncio.run(gen(runner=SdkAgentRunner(), model=os.environ.get("BACKLOG_MODEL", _DEFAULT_MODEL),
                          timeout_s=float(os.environ.get("BACKLOG_TIMEOUT_S", "300")),
                          brd_sections=sections, known_refs=known_refs,
                          known_requirement_ids=sorted(known_req_ids)))
    backlog = parse_backlog_payload(raw, repo_slug=slug, known_refs=set(known_refs),
                                    known_requirement_ids=known_req_ids)
    try:
        seam_candidates = rank_candidates(neo4j, repo=slug)
    except _NEO4J_ERRORS:
        logger.warning("backlog: seam ranking failed for %s — deriving DAG without seams", slug)
        seam_candidates = []
    dag = derive_story_dependencies(backlog.stories, seam_candidates, repo_slug=slug)
    backlog.stories = dag.stories
    backlog.evidence_map = {s.id: s.evidence_refs for s in backlog.stories}

    report = brd_logic_coverage(neo4j, slug, sections, backlog.evidence_map)
    coverage = report.model_dump(mode="json")
    BacklogStorage(neo4j).save(backlog, coverage=coverage,
                               html=render_html(backlog, coverage))

    min_cov = _coverage_min()
    passed = report.coverage_ratio >= min_cov
    threshold = {"min_coverage": min_cov}
    result = {"coverage_ratio": report.coverage_ratio, "uncovered": report.uncovered_refs[:50]}
    upsert_gate(session, workspace.id, "backlog", "backlog_coverage",
                passed=passed, result=result, threshold=threshold)
    upsert_gate(session, workspace.id, "blueprint", "brd_logic_coverage",
                passed=passed, result=result, threshold=threshold)
    session.flush()
    return {"repo_slug": slug, "epics": len(backlog.epics), "stories": len(backlog.stories),
            "coverage_ratio": report.coverage_ratio, "version": backlog.version}


@router.post("/workspaces/{wid}/backlog", status_code=202)
def backlog_generate(wid: str, session: Session = Depends(get_session),
                     neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    if not os.environ.get("ANTHROPIC_API_KEY") and not jobs.runner.inline:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not set — Backlog needs an LLM.")

    def _job() -> dict:
        s = jobs.make_session()
        neo = jobs.make_neo4j()
        try:
            ws2 = s.get(Workspace, wid)
            out = run_backlog(session=s, neo4j=neo, workspace=ws2)
            s.commit()
            return out
        finally:
            s.close()
            try:
                neo.close()
            except Exception:  # noqa: BLE001
                pass

    return _job_view(jobs.runner.start("backlog", wid, _job))


@router.get("/workspaces/{wid}/backlog")
def backlog_status(wid: str, session: Session = Depends(get_session),
                   neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    job = jobs.runner.get("backlog", wid)
    if job is not None:
        return _job_view(job)
    try:
        latest = BacklogStorage(neo4j).get_latest(ws.repo_slug)
    except _NEO4J_ERRORS:
        latest = None
    if latest:
        cov = json.loads(latest.get("coverage_json") or "{}")
        return {"status": "done", "error": None,
                "result": {"repo_slug": ws.repo_slug, "version": latest.get("version"),
                           "epics": len(json.loads(latest.get("epics_json") or "[]")),
                           "stories": len(json.loads(latest.get("stories_json") or "[]")),
                           "coverage_ratio": cov.get("coverage_ratio")}}
    return {"status": "idle", "result": None, "error": None}


@router.get("/workspaces/{wid}/backlog/html", response_class=HTMLResponse)
def backlog_html(wid: str, session: Session = Depends(get_session),
                 neo4j=Depends(get_neo4j)) -> HTMLResponse:
    ws = _workspace(session, wid)
    try:
        latest = BacklogStorage(neo4j).get_latest(ws.repo_slug)
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")
    if not latest or not latest.get("html"):
        raise HTTPException(status_code=404, detail="no backlog yet — run the Backlog stage first")
    return HTMLResponse(content=latest["html"])
