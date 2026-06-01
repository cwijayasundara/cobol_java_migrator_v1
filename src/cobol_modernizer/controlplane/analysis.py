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
from cobol_modernizer.design.adr import default_adrs_for_writer_slice
from cobol_modernizer.design.context_map import assign_context
from cobol_modernizer.design.judge import judge_design
from cobol_modernizer.design.schema import BoundedContext, ServiceDesign
from cobol_modernizer.persistence.tables import JourneyStage, Workspace
from cobol_modernizer.planner.dag import is_acyclic, topo_order
from cobol_modernizer.planner.dependency import derive_dependencies, stories_from_seam_set
from cobol_modernizer.seam.service import rank_candidates

_WRITES_BY_PROGRAM = """
MATCH (p:CodeEntity {repo:$repo}) WHERE p.kind = 'Program'
OPTIONAL MATCH (p)-[w:WRITES]->(x:CodeEntity)
RETURN p.qualified_name AS program,
       collect(DISTINCT coalesce(w.resource, x.simple_name, x.qualified_name)) AS writes
"""

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


class _WriterAdapter:
    """Satisfies design.context_map._WriterDeps: program -> resources it WRITES."""
    def __init__(self, writes_by_program: dict[str, list[str]]) -> None:
        self._w = writes_by_program

    def writer_resources(self, program: str) -> list[str]:
        return self._w.get(program, [])


@router.post("/workspaces/{wid}/design")
def run_design(wid: str, session: Session = Depends(get_session),
               neo4j=Depends(get_neo4j)) -> dict:
    """Deterministic service design for each WRITER slice: bounded-context
    assignment (from owned/written resources) + template ADRs (modular monolith,
    Extract Product Lines, Legacy Mimic) + the data-ownership/groundedness gate.
    No LLM."""
    ws = _workspace(session, wid)
    try:
        rows = neo4j.run(_WRITES_BY_PROGRAM, repo=ws.repo_slug)
        known_refs = {r["q"] for r in neo4j.run(
            "MATCH (n:CodeEntity {repo:$repo}) RETURN n.qualified_name AS q",
            repo=ws.repo_slug)}
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")

    writes_by_program: dict[str, list[str]] = {
        r["program"]: [w for w in (r.get("writes") or []) if w] for r in rows
    }
    if not known_refs:
        raise HTTPException(status_code=409,
                            detail="no graph — run the Parse stage first")
    # resource -> every program that writes it (for ownership-leak detection)
    writers_of: dict[str, list[str]] = {}
    for prog, res_list in writes_by_program.items():
        for res in res_list:
            writers_of.setdefault(res, []).append(prog)

    adapter = _WriterAdapter(writes_by_program)
    designs: list[dict] = []
    for prog in sorted(p for p, w in writes_by_program.items() if w):
        owned = sorted(set(writes_by_program[prog]))
        try:
            context = assign_context(adapter, prog)
        except ValueError:
            continue  # owns resources with no known context — skip
        external = {res: [w for w in writers_of.get(res, []) if w != prog]
                    for res in owned if any(w != prog for w in writers_of.get(res, []))}
        design = ServiceDesign(
            slice_id=f"{prog}-slice", context=BoundedContext(context),
            owned_resources=owned, transition_pattern="extract_product_lines+legacy_mimic",
            components=[f"{prog}Service", f"{prog}Repository"],
            evidence_map={"DR-1": [prog]})
        adrs = default_adrs_for_writer_slice(slice_id=design.slice_id,
                                             owned_resources=owned, evidence_refs=[prog])
        report = judge_design(design, known_refs=known_refs, external_writers=external)
        designs.append({
            "design": design.model_dump(mode="json"),
            "adrs": [a.model_dump(mode="json") for a in adrs],
            "rating": report.rating, "data_ownership_ok": report.data_ownership_ok,
            "groundedness_failures": report.groundedness_failures,
            "rationale": report.rationale,
        })

    _mark_passed(session, wid, "design")
    session.flush()
    return {"repo_slug": ws.repo_slug, "count": len(designs), "designs": designs}
