"""Technical Design stage (the cockpit's 'design' stage) — DDD contexts + backlog +
seam waves → target service architecture. Mirrors blueprint.py. Replaces the legacy
deterministic writer-slice design. Upserts the design_data_ownership gate (every
writer resource owned by exactly one service)."""
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
from cobol_modernizer.backlog.storage import BacklogStorage
from cobol_modernizer.controlplane import jobs
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.controlplane.domain import DomainDesignStorage
from cobol_modernizer.controlplane.gates_util import upsert_gate
from cobol_modernizer.persistence.tables import Workspace
from cobol_modernizer.seam.service import rank_candidates
from cobol_modernizer.technical_design.generator import (
    generate_technical_design_payload,
    parse_technical_design_payload,
)
from cobol_modernizer.technical_design.render import render_html
from cobol_modernizer.technical_design.storage import TechnicalDesignStorage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["controlplane-technical-design"])
_NEO4J_ERRORS = (Neo4jError, DriverError)
_GRAPH_REFS_Q = "MATCH (n:CodeEntity {repo:$repo}) RETURN n.qualified_name AS q"
_DEFAULT_MODEL = "claude-sonnet-4-6"


def _workspace(session: Session, wid: str) -> Workspace:
    ws = session.get(Workspace, wid)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"workspace {wid} not found")
    return ws


def _job_view(job: dict | None) -> dict:
    if job is None:
        return {"status": "idle", "result": None, "error": None,
                "started_at": None, "finished_at": None}
    return {"status": job["status"], "result": job.get("result"), "error": job.get("error"),
            "started_at": job.get("started_at"), "finished_at": job.get("finished_at")}


def _data_ownership_ok(design) -> tuple[bool, list[str]]:
    """Every writer resource owned by exactly one service. Returns (ok, conflicts)."""
    owners: dict[str, list[str]] = {}
    for svc in design.services:
        for p in svc.persistence:
            owners.setdefault(p.resource, []).append(svc.name)
    conflicts = [res for res, svcs in owners.items() if len(svcs) > 1]
    return (not conflicts), conflicts


def run_technical_design(*, session: Session, neo4j, workspace: Workspace,
                         generate: Callable[..., Any] | None = None) -> dict:
    slug = workspace.repo_slug
    dd = DomainDesignStorage(neo4j).get_latest(slug)
    if not dd:
        raise HTTPException(status_code=409, detail=f"no domain design for '{slug}' — run Domain Design first")
    raw_ctx = dd.get("contexts_json")
    try:
        contexts = json.loads(raw_ctx or "[]")
    except json.JSONDecodeError:
        logger.warning("technical_design: malformed contexts_json for %s — treating as empty", slug)
        contexts = []
    known_contexts = {c.get("name") for c in contexts if isinstance(c, dict) and c.get("name")}
    backlog = BacklogStorage(neo4j).get_latest(slug)
    if backlog:
        try:
            stories = json.loads(backlog.get("stories_json") or "[]")
        except json.JSONDecodeError:
            logger.warning("technical_design: malformed stories_json for %s — treating as empty", slug)
            stories = []
    else:
        stories = []
    known_story_ids = {s.get("id") for s in stories if isinstance(s, dict) and s.get("id")}
    known_refs = {r["q"] for r in neo4j.run(_GRAPH_REFS_Q, repo=slug) if r.get("q")}
    try:
        seam_waves = [[c.get("program")] for c in rank_candidates(neo4j, repo=slug)]
    except _NEO4J_ERRORS:
        logger.warning("technical_design: seam ranking failed for %s — using empty waves", slug)
        seam_waves = []

    # Ensure a :Repository node exists for TechnicalDesignStorage (uses MATCH, like blueprint/backlog).
    neo4j.run("MERGE (r:Repository {slug: $slug}) SET r.name = coalesce(r.name, $slug)", slug=slug)

    gen = generate or generate_technical_design_payload
    raw = asyncio.run(gen(runner=SdkAgentRunner(),
                          model=os.environ.get("TECHNICAL_DESIGN_MODEL", _DEFAULT_MODEL),
                          timeout_s=float(os.environ.get("TECHNICAL_DESIGN_TIMEOUT_S", "300")),
                          ddd_json=json.dumps({"contexts": contexts}),
                          backlog_json=json.dumps({"stories": stories}),
                          seam_waves_json=json.dumps(seam_waves),
                          graph_summary={"refs": sorted(known_refs)[:200]}))
    design = parse_technical_design_payload(raw, repo_slug=slug, known_refs=known_refs,
                                            known_story_ids=known_story_ids,
                                            known_contexts=known_contexts)
    TechnicalDesignStorage(neo4j).save(design, html=render_html(design))

    ok, conflicts = _data_ownership_ok(design)
    upsert_gate(session, workspace.id, "design", "design_data_ownership",
                passed=ok, result={"conflicts": conflicts},
                threshold={"unique_writer_ownership": True})
    session.flush()
    return {"repo_slug": slug, "services": len(design.services),
            "data_ownership_ok": ok, "version": design.version}


@router.post("/workspaces/{wid}/technical-design", status_code=202)
def technical_design_generate(wid: str, session: Session = Depends(get_session),
                              neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    if not os.environ.get("ANTHROPIC_API_KEY") and not jobs.runner.inline:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not set — Technical Design needs an LLM.")

    def _job() -> dict:
        s = jobs.make_session()
        neo = jobs.make_neo4j()
        try:
            ws2 = s.get(Workspace, wid)
            out = run_technical_design(session=s, neo4j=neo, workspace=ws2)
            s.commit()
            return out
        finally:
            s.close()
            try:
                neo.close()
            except Exception:  # noqa: BLE001
                pass

    return _job_view(jobs.runner.start("technical_design", wid, _job))


@router.get("/workspaces/{wid}/technical-design")
def technical_design_status(wid: str, session: Session = Depends(get_session),
                            neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    job = jobs.runner.get("technical_design", wid)
    if job is not None:
        return _job_view(job)
    try:
        latest = TechnicalDesignStorage(neo4j).get_latest(ws.repo_slug)
    except _NEO4J_ERRORS:
        latest = None
    if latest:
        return {"status": "done", "error": None, "started_at": None, "finished_at": None,
                "result": {"repo_slug": ws.repo_slug, "version": latest.get("version"),
                           "services": len(json.loads(latest.get("services_json") or "[]"))}}
    return {"status": "idle", "result": None, "error": None, "started_at": None, "finished_at": None}


@router.get("/workspaces/{wid}/technical-design/html", response_class=HTMLResponse)
def technical_design_html(wid: str, session: Session = Depends(get_session),
                          neo4j=Depends(get_neo4j)) -> HTMLResponse:
    ws = _workspace(session, wid)
    try:
        latest = TechnicalDesignStorage(neo4j).get_latest(ws.repo_slug)
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")
    if not latest or not latest.get("html"):
        raise HTTPException(status_code=404, detail="no technical design yet — run the Design stage first")
    return HTMLResponse(content=latest["html"])
