"""POST /api/workspaces/{id}/parse — the deterministic parse→graph step.

Runs the real COBOL extractor on the workspace's repo (resolved from its
repo_slug under $COBOL_SOURCE_ROOT), ingests the entities/relationships into Neo4j
tagged with that repo, marks the `parse` + `graph` journey stages passed, and
returns counts. No LLM here — this is the deterministic analysis core wired to a
button so the cockpit's Parse and Graph stages actually do something."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from neo4j.exceptions import DriverError, Neo4jError
from sqlalchemy import select
from sqlalchemy.orm import Session

from cobol_modernizer.cobol.parser import CobolParser
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.controlplane.repos import discover_copybook_dirs
from cobol_modernizer.ingestion import ingest_parse_results
from cobol_modernizer.persistence.tables import JourneyStage, Workspace

router = APIRouter(prefix="/api", tags=["controlplane-parse"])


def _source_root() -> Path:
    return Path(os.environ.get("COBOL_SOURCE_ROOT", "source_code_to_analyse"))


def _mark_passed(session: Session, workspace_id: str, stage_keys: list[str]) -> None:
    rows = session.execute(
        select(JourneyStage).where(
            JourneyStage.workspace_id == workspace_id,
            JourneyStage.stage_key.in_(stage_keys))
    ).scalars().all()
    for st in rows:
        st.status = "passed"


def run_parse(*, session: Session, neo4j, workspace: Workspace, source_root: Path,
              parser_factory: Callable[..., Any] | None = None) -> dict[str, Any]:
    """Parse + ingest the workspace's repo. parser_factory defaults to CobolParser
    (resolved at call time so tests can monkeypatch parse.CobolParser)."""
    factory = parser_factory or CobolParser
    repo_dir = source_root / workspace.repo_slug
    if not repo_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"repo directory '{workspace.repo_slug}' not found under {source_root}")
    parser = factory(
        repo_dir,
        jar_path=os.environ.get("COBOL_EXTRACTOR_JAR"),
        copybook_dirs=tuple(discover_copybook_dirs(repo_dir)),
        source_format=os.environ.get("COBOL_MOD_COBOL_FORMAT", "FIXED"),
        java_home=os.environ.get("JAVA_HOME"),
    )
    results = parser.parse_repo()
    if not results:
        raise HTTPException(
            status_code=503,
            detail="extractor produced no results — check COBOL_EXTRACTOR_JAR and a "
                   "working JAVA_HOME (the macOS /usr/bin/java stub is not a JDK).")

    programs = sum(1 for r in results for e in r.entities if e.kind.value == "Program")
    copybooks = sum(1 for r in results for e in r.entities if e.kind.value == "Copybook")
    parse_errors = sum(1 for r in results if not r.entities and not r.relationships)
    counts = ingest_parse_results(neo4j, results, repo=workspace.repo_slug)

    _mark_passed(session, workspace.id, ["parse", "graph"])
    session.flush()
    return {
        "repo_slug": workspace.repo_slug,
        "programs": programs, "copybooks": copybooks, "parse_errors": parse_errors,
        "entities": counts["entities"], "relationships": counts["relationships"],
    }


@router.post("/workspaces/{wid}/parse")
def parse_workspace(wid: str, session: Session = Depends(get_session),
                    neo4j=Depends(get_neo4j)) -> dict:
    ws = session.get(Workspace, wid)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"workspace {wid} not found")
    try:
        return run_parse(session=session, neo4j=neo4j, workspace=ws,
                         source_root=_source_root())
    except HTTPException:
        raise
    except (Neo4jError, DriverError) as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")
    except subprocess.CalledProcessError as exc:
        raise HTTPException(status_code=503,
                            detail=f"COBOL extractor failed (exit {exc.returncode})")
