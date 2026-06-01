"""Build stage — TDD codegen for a writer slice, grounded in the parsed graph.

POST /api/workspaces/{id}/build asks the codegen agent to emit a Java slice
(JUnit tests FIRST, then minimal Spring Boot code) navigating the repo's Neo4j
graph, scaffolds a Maven module (Spring Boot + the four quality gates: ArchUnit,
SpotBugs/FindSecBugs, Error Prone, Checkstyle), writes the generated files into
it, and marks the `build` stage passed. Needs ANTHROPIC_API_KEY and a parsed
graph; run Blueprint first (the BRD is the codegen brief).

Compiling + running the quality gates (`mvn verify`) is a separate, slower,
host-dependent step (needs Maven + a JDK and a reconciled Spring Boot/Java pair),
so the endpoint produces the source artifact + scaffold, not a compiled jar. The
QualityReport parser (codegen.quality_gate) is the seam for a later CI step."""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from neo4j.exceptions import DriverError, Neo4jError
from sqlalchemy import select
from sqlalchemy.orm import Session

from cobol_modernizer.brd.storage import BRDStorage
from cobol_modernizer.codegen.scaffold import scaffold_module
from cobol_modernizer.codegen.schema import GeneratedProject
from cobol_modernizer.controlplane import jobs
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.persistence.tables import JourneyStage, Workspace

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["controlplane-build"])
_NEO4J_ERRORS = (Neo4jError, DriverError)
_PKG_SAFE = re.compile(r"[^a-z0-9]+")


def _source_root() -> Path:
    return Path(os.environ.get("COBOL_SOURCE_ROOT", "source_code_to_analyse"))


def _output_root() -> Path:
    return Path(os.environ.get("CODEGEN_OUTPUT_DIR", "codegen_output"))


def _base_package(slug: str) -> str:
    leaf = _PKG_SAFE.sub("", slug.split("/")[-1].lower()) or "app"
    return f"com.cobolmodernizer.{leaf}"


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


def _generate_slice_graph(slug: str, *, neo4j, repo_path: str,
                          brd_json: str) -> GeneratedProject:
    """Real codegen: build the read-only graph MCP server + SDK runner and run the
    TDD codegen agent over this repo's graph. Imported lazily so the agent SDK is
    only required when an actual generation runs (tests inject a stub instead)."""
    import asyncio

    from cobol_modernizer.agent.deps import GraphDeps
    from cobol_modernizer.agent.graph_tools import GRAPH_TOOL_NAMES, build_graph_server
    from cobol_modernizer.agent.harness import SdkAgentRunner
    from cobol_modernizer.codegen.generator import generate_slice
    from cobol_modernizer.cost.tiering import resolve_model

    deps = GraphDeps(client=neo4j, repo_id=slug, repo_path=Path(repo_path))
    server = build_graph_server(deps)
    runner = SdkAgentRunner()
    return asyncio.run(generate_slice(
        runner=runner, server=server, model=resolve_model("codegen"),
        brd_json=brd_json, golden_summary="(no recorded golden master yet)",
        allowed_tools=GRAPH_TOOL_NAMES))


def _precheck(neo4j, workspace: Workspace, source_root: Path) -> dict:
    """Fast, synchronous validation before queueing the multi-minute codegen job:
    repo dir present + a BRD exists (the codegen brief). Returns the latest BRD."""
    slug = workspace.repo_slug
    if not (source_root / slug).is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"repo directory '{slug}' not found under {source_root}")
    latest = BRDStorage(neo4j).get_latest(slug)
    if not latest:
        raise HTTPException(status_code=409,
                            detail="no BRD — run the Blueprint stage first")
    return latest


def run_build(*, session: Session, neo4j, workspace: Workspace,
              source_root: Path, output_root: Path,
              generate: Callable[..., GeneratedProject] | None = None) -> dict[str, Any]:
    """Generate a slice + scaffold a Maven module + write the files. `generate`
    defaults to the real graph codegen (resolved here so tests can inject a stub)."""
    slug = workspace.repo_slug
    repo_dir = source_root / slug
    latest = _precheck(neo4j, workspace, source_root)
    brd_json = json.dumps({"repo_id": slug, "version": latest.get("version"),
                           "rating": latest.get("rating")})

    logger.info("build: generating slice for repo=%s (BRD v%s) — multi-minute LLM run",
                slug, latest.get("version"))
    gen = generate or _generate_slice_graph
    project = gen(slug, neo4j=neo4j, repo_path=str(repo_dir.resolve()),
                  brd_json=brd_json)

    base_package = _base_package(slug)
    module = f"{_PKG_SAFE.sub('-', slug.split('/')[-1].lower())}-{project.slice_id}"
    root = scaffold_module(output_root, module=module, base_package=base_package)
    for f in project.files:
        dest = root / f.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f.content, encoding="utf-8")

    _mark_passed(session, workspace.id, "build")
    session.flush()
    files = [{"path": f.path, "kind": f.kind, "evidence": f.evidence}
             for f in project.files]
    return {
        "repo_slug": slug, "slice_id": project.slice_id, "module": module,
        "base_package": base_package, "scaffold_path": str(root),
        "file_count": len(project.files),
        "tests": sum(1 for f in project.files if f.kind == "test"),
        "mains": sum(1 for f in project.files if f.kind == "main"),
        "files": files, "evidence_map": project.evidence_map,
    }


def _job_view(job: dict) -> dict:
    return {"status": job["status"], "result": job.get("result"),
            "error": job.get("error"), "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at")}


@router.post("/workspaces/{wid}/build", status_code=202)
def build_workspace(wid: str, session: Session = Depends(get_session),
                    neo4j=Depends(get_neo4j)) -> dict:
    """Kick off the (multi-minute) codegen run as a background job and return 202;
    the UI polls GET .../build. Validates fast first (key / repo dir / BRD present).
    A TDD violation surfaces as a 'failed' job (error in the GET status)."""
    ws = _workspace(session, wid)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=503,
                            detail="ANTHROPIC_API_KEY not set — Build needs an LLM.")
    try:
        _precheck(neo4j, ws, _source_root())
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")

    def _job() -> dict:
        s = jobs.make_session()
        neo = jobs.make_neo4j()
        try:
            ws2 = s.get(Workspace, wid)
            result = run_build(session=s, neo4j=neo, workspace=ws2,
                               source_root=_source_root(), output_root=_output_root())
            s.commit()
            return result
        finally:
            s.close()
            try:
                neo.close()
            except Exception:  # noqa: BLE001
                pass

    logger.info("build: queued background run for workspace=%s repo=%s",
                wid, ws.repo_slug)
    return _job_view(jobs.runner.start("build", wid, _job))


@router.get("/workspaces/{wid}/build")
def build_status(wid: str, session: Session = Depends(get_session),
                 neo4j=Depends(get_neo4j)) -> dict:
    """Poll the background codegen job (running / done+manifest / failed+error)."""
    _workspace(session, wid)
    job = jobs.runner.get("build", wid)
    if job is None:
        return {"status": "idle", "result": None, "error": None,
                "started_at": None, "finished_at": None}
    return _job_view(job)
