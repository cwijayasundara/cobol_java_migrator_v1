"""Analysis stages wired to the parsed Neo4j graph.

Deterministic (no LLM) — run over the parsed graph, 409 if not yet parsed:
- POST /api/workspaces/{id}/seams — ranked strangler-fig seam candidates
  (reader/writer split, blast radius, testability, data-ownership, risk), via the
  seam engine's pure-Cypher scorer.
- POST /api/workspaces/{id}/plan — an acyclic story DAG derived from those seams
  (deterministic dependency derivation + topological order + delivery waves; the
  LLM INVEST judge from the full pipeline is intentionally skipped here).
  (The deterministic writer-slice design POST has been retired; the cockpit's
  Design stage now lives in controlplane/technical_design.py.)

LLM enrichment (opt-in, multi-minute background jobs; ANTHROPIC_API_KEY required) —
these only ADD narrative on top of the deterministic output and degrade to
deterministic-only on failure/timeout:
- POST {seams,plan,design}/enrich — start a batched enrichment job (seam rationale /
  per-story INVEST + delivery narrative / design ADR+component+API elaboration).
- GET  {seams,plan,design}/enrichment — poll the job and fetch the narrative payload."""
from __future__ import annotations

import asyncio
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from neo4j.exceptions import DriverError, Neo4jError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from cobol_modernizer.agent.harness import SdkAgentRunner
from cobol_modernizer.brd.storage import BRDStorage
from cobol_modernizer.controlplane import jobs
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.controlplane.domain import DomainDesignStorage, run_domain_design
from cobol_modernizer.controlplane.enrichment_store import EnrichmentStorage
from cobol_modernizer.controlplane.gates_util import upsert_gate
from cobol_modernizer.domain.render import render_html
from cobol_modernizer.domain.quality import assess_domain_quality
from cobol_modernizer.design.adr import default_adrs_for_writer_slice
from cobol_modernizer.design.context_map import assign_context
from cobol_modernizer.design.judge import judge_design
from cobol_modernizer.design.schema import ServiceDesign
from cobol_modernizer.enrichment.config import enrich_model, enrich_timeout_s
from cobol_modernizer.enrichment.design import enrich_design
from cobol_modernizer.enrichment.plan import enrich_plan
from cobol_modernizer.enrichment.seams import enrich_seams
from cobol_modernizer.persistence.tables import Gate, JourneyStage, Workspace
from cobol_modernizer.persistence.repo import PgRepo
from cobol_modernizer.planner.dag import delivery_waves, is_acyclic, topo_order
from cobol_modernizer.planner.dependency import derive_dependencies, stories_from_seam_set
from cobol_modernizer.planner.quality import assess_plan_quality
from cobol_modernizer.seam.quality import assess_seam_quality
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


def _mark_stage_status(session: Session, wid: str, stage_key: str, status: str) -> None:
    for st in session.execute(
        select(JourneyStage).where(JourneyStage.workspace_id == wid,
                                   JourneyStage.stage_key == stage_key)
    ).scalars().all():
        st.status = status


def _has_blocking_work_units(repo: PgRepo, *, workspace_id: str, stage: str) -> bool:
    return any(
        u.status in {"failed", "deferred"}
        for u in repo.list_work_units(workspace_id=workspace_id, stage=stage)
    )


def _stage_status(session: Session, wid: str, stage_key: str) -> str | None:
    return session.execute(
        select(JourneyStage.status).where(JourneyStage.workspace_id == wid,
                                          JourneyStage.stage_key == stage_key)
    ).scalars().first()


def _ranked(neo4j, repo: str, limit: int = 25) -> list[dict]:
    try:
        return rank_candidates(neo4j, repo=repo, limit=limit)
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")


_KNOWN_REFS_Q = "MATCH (n:CodeEntity {repo:$repo}) RETURN n.qualified_name AS q"


def _known_refs(neo4j, slug: str) -> set[str]:
    return {r["q"] for r in neo4j.run(_KNOWN_REFS_Q, repo=slug)}


def _job_view(job: dict | None) -> dict:
    if job is None:
        return {"status": "idle", "result": None, "error": None}
    return {"status": job["status"], "result": job.get("result"),
            "error": job.get("error")}


def _work_unit_progress(session: Session, wid: str, stage: str) -> dict:
    units = PgRepo(session).list_work_units(workspace_id=wid, stage=stage)
    counts: dict[str, int] = {}
    for unit in units:
        counts[unit.status] = counts.get(unit.status, 0) + 1
    return {
        "total": len(units),
        "counts": counts,
        "units": [{
            "id": u.id, "stage": u.stage, "unit_type": u.unit_type,
            "unit_key": u.unit_key, "input_hash": u.input_hash,
            "status": u.status, "attempt": u.attempt,
            "model": u.model, "error_cause": u.error_cause,
            "started_at": u.started_at.isoformat() if u.started_at else None,
            "finished_at": u.finished_at.isoformat() if u.finished_at else None,
        } for u in units],
    }


def _gate_view(session: Session, wid: str, gate_key: str) -> dict | None:
    gate = session.execute(
        select(Gate).where(Gate.workspace_id == wid, Gate.gate_key == gate_key)
    ).scalars().first()
    if gate is None:
        return None
    return {
        "gate_key": gate.gate_key,
        "status": gate.status,
        "result": gate.result or {},
        "threshold": gate.threshold or {},
        "updated_at": gate.updated_at.isoformat() if gate.updated_at else None,
    }


def _domain_quality_response(session: Session, wid: str) -> dict:
    gate = _gate_view(session, wid, "domain_quality")
    return {
        "quality_gate": gate,
        "quality": gate["result"] if gate else None,
        "quality_threshold": gate["threshold"] if gate else None,
        "quality_passed": (gate["status"] == "passed") if gate else None,
    }


def _require_llm() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=503,
                            detail="ANTHROPIC_API_KEY not set — enrichment needs an LLM.")


logger = logging.getLogger(__name__)


def _enrich_limit(kind: str, default: int) -> int:
    raw = os.environ.get(f"{kind.upper()}_ENRICH_LIMIT")
    if raw is None:
        raw = os.environ.get("ANALYSIS_ENRICH_LIMIT", str(default))
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _persist_enrichment(neo, slug: str, kind: str, payload: dict) -> None:
    """Best-effort save of an enrichment result so it survives restarts + is reused.
    Never fails the job — a persistence hiccup must not lose the freshly-computed result."""
    try:
        neo.run("MERGE (r:Repository {slug:$slug})", slug=slug)
        EnrichmentStorage(neo).save(slug, kind, payload)
    except Exception:  # noqa: BLE001
        logger.warning("could not persist %s enrichment for %s", kind, slug, exc_info=True)


def _saved_enrichment(neo, slug: str, kind: str):
    """Latest persisted enrichment payload for (slug, kind), or None. Uses the caller's
    (request-scoped, test-injectable) neo client."""
    try:
        return EnrichmentStorage(neo).get_latest(slug, kind)
    except _NEO4J_ERRORS:
        return None


def _start_or_reuse_enrich(wid: str, slug: str, kind: str, compute, refresh: bool,
                           neo4j) -> dict:
    """Reuse the persisted enrichment (no LLM) unless `refresh`; otherwise run the job,
    which persists its result on completion. `compute(neo) -> payload dict`. The reuse
    check uses the request-scoped `neo4j`; the job opens its own connection (it runs on a
    background thread, after the request neo4j is gone)."""
    if not refresh:
        saved = _saved_enrichment(neo4j, slug, kind)
        if saved is not None:
            return {"status": "done", "error": None, "result": saved}

    def _job() -> dict:
        neo = jobs.make_neo4j()
        try:
            payload = compute(neo)
            _persist_enrichment(neo, slug, kind, payload)
            return payload
        finally:
            try:
                neo.close()
            except Exception:  # noqa: BLE001
                pass

    return _job_view(jobs.runner.start(f"{kind}-enrich", wid, _job))


def _enrichment_view(wid: str, slug: str, kind: str, neo4j) -> dict:
    """In-flight job view if one exists, else the persisted result (restart-safe), else idle."""
    job = jobs.runner.get(f"{kind}-enrich", wid)
    if job is not None:
        return _job_view(job)
    saved = _saved_enrichment(neo4j, slug, kind)
    if saved is not None:
        return {"status": "done", "error": None, "result": saved}
    return {"status": "idle", "result": None, "error": None}


@router.post("/workspaces/{wid}/seams")
def run_seams(wid: str, session: Session = Depends(get_session),
              neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    cands = _ranked(neo4j, ws.repo_slug)
    if not cands:
        raise HTTPException(status_code=409,
                            detail="no seam candidates — run the Parse stage first")
    passed, result, threshold = assess_seam_quality(cands, known_refs=_known_refs(neo4j, ws.repo_slug))
    upsert_gate(session, wid, "seams", "seams_quality",
                passed=passed, result=result, threshold=threshold)
    _mark_stage_status(session, wid, "seams", "passed" if passed else "incomplete")
    session.flush()
    return {"repo_slug": ws.repo_slug, "count": len(cands), "candidates": cands,
            "quality": result, "quality_passed": passed}


@router.post("/workspaces/{wid}/seams/enrich", status_code=202)
def seams_enrich(wid: str, refresh: bool = False,
                 session: Session = Depends(get_session),
                 neo4j=Depends(get_neo4j)) -> dict:
    """Batched seam-rationale enrichment. Reuses the persisted result if one exists
    (no LLM); pass ?refresh=true to force a fresh multi-minute run. Deterministic seams
    are unaffected; this only ADDS narrative, which is persisted + reused."""
    ws = _workspace(session, wid)
    _require_llm()
    slug = ws.repo_slug

    def compute(neo) -> dict:
        cands = _ranked(neo, slug, limit=_enrich_limit("seams", 10))
        known = _known_refs(neo, slug)
        runner = SdkAgentRunner()
        narratives = asyncio.run(enrich_seams(
            cands, known, runner=runner, model=enrich_model("seams"),
            timeout_s=enrich_timeout_s("seams")))
        return {"repo_slug": slug, "narratives": narratives,
                "token_usage": dict(runner.token_usage)}

    return _start_or_reuse_enrich(wid, slug, "seams", compute, refresh, neo4j)


@router.get("/workspaces/{wid}/seams/enrichment")
def seams_enrichment(wid: str, session: Session = Depends(get_session),
                     neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    return _enrichment_view(wid, ws.repo_slug, "seams", neo4j)


@router.post("/workspaces/{wid}/plan/enrich", status_code=202)
def plan_enrich(wid: str, refresh: bool = False,
                session: Session = Depends(get_session),
                neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    _require_llm()
    slug = ws.repo_slug

    def compute(neo) -> dict:
        cands = _ranked(neo, slug, limit=_enrich_limit("plan", 12))
        stories = stories_from_seam_set(cands, repo_id=slug)
        dag = derive_dependencies(stories, cands, repo_id=slug)
        waves = delivery_waves(dag) if is_acyclic(dag) else []
        known = _known_refs(neo, slug)
        runner = SdkAgentRunner()
        result = asyncio.run(enrich_plan(
            [s.model_dump(mode="json") for s in dag.stories], waves, known,
            runner=runner, model=enrich_model("plan"),
            timeout_s=enrich_timeout_s("plan")))
        return {"repo_slug": slug, **result, "token_usage": dict(runner.token_usage)}

    return _start_or_reuse_enrich(wid, slug, "plan", compute, refresh, neo4j)


@router.get("/workspaces/{wid}/plan/enrichment")
def plan_enrichment(wid: str, session: Session = Depends(get_session),
                    neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    return _enrichment_view(wid, ws.repo_slug, "plan", neo4j)


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
    # Best-effort: tag stories with their bounded context if a domain-design exists.
    # Purely optional enrichment — it must NEVER break planning, so swallow anything
    # (missing graph, malformed JSON, a stub client without .run in tests).
    try:
        latest = DomainDesignStorage(neo4j).get_latest(ws.repo_slug)
        if latest:
            import json as _json
            from cobol_modernizer.planner.tagging import tag_stories_with_contexts
            tag_stories_with_contexts(dag.stories, _json.loads(latest.get("contexts_json") or "[]"))
    except Exception:  # noqa: BLE001 — story tagging is optional, never fatal to run_plan
        pass
    acyclic = is_acyclic(dag)
    order = topo_order(dag) if acyclic else []
    waves = delivery_waves(dag) if acyclic else []
    passed, result, threshold = assess_plan_quality(
        dag, seam_candidates=cands, acyclic=acyclic,
        topo_order=order, delivery_waves=waves)
    upsert_gate(session, wid, "plan", "stories_dag",
                passed=passed, result=result, threshold=threshold)
    upsert_gate(session, wid, "plan", "plan_quality",
                passed=passed, result=result, threshold=threshold)
    _mark_stage_status(session, wid, "plan", "passed" if passed else "incomplete")
    session.flush()
    return {
        "repo_slug": ws.repo_slug, "acyclic": acyclic, "topo_order": order,
        "delivery_waves": waves,
        "stories": [s.model_dump(mode="json") for s in dag.stories],
        "quality": result, "quality_passed": passed,
    }


class _WriterAdapter:
    """Satisfies design.context_map._WriterDeps: program -> resources it WRITES."""
    def __init__(self, writes_by_program: dict[str, list[str]]) -> None:
        self._w = writes_by_program

    def writer_resources(self, program: str) -> list[str]:
        return self._w.get(program, [])


def _compute_designs(neo4j, slug: str) -> list[dict]:
    """The deterministic per-writer-slice design list (the same data run_design
    returns under 'designs'). Extracted so the enrich job can reuse it."""
    rows = neo4j.run(_WRITES_BY_PROGRAM, repo=slug)
    known_refs = _known_refs(neo4j, slug)
    writes_by_program = {r["program"]: [w for w in (r.get("writes") or []) if w]
                         for r in rows}
    if not known_refs:
        raise HTTPException(status_code=409,
                            detail="no graph — run the Parse stage first")
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
            continue
        external = {res: [w for w in writers_of.get(res, []) if w != prog]
                    for res in owned if any(w != prog for w in writers_of.get(res, []))}
        design = ServiceDesign(
            slice_id=f"{prog}-slice", context=context,
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
    return designs


@router.post("/workspaces/{wid}/design/enrich", status_code=202)
def design_enrich(wid: str, refresh: bool = False,
                  session: Session = Depends(get_session),
                  neo4j=Depends(get_neo4j)) -> dict:
    """Legacy per-slice design narrative (the cockpit's Design→Improve now derives from
    Domain Design instead). Kept + now persisted/reused for API back-compat; ?refresh=true
    forces a fresh run."""
    ws = _workspace(session, wid)
    _require_llm()
    slug = ws.repo_slug

    def compute(neo) -> dict:
        designs = _compute_designs(neo, slug)
        known = _known_refs(neo, slug)
        runner = SdkAgentRunner()
        narratives = asyncio.run(enrich_design(
            designs, known, runner=runner, model=enrich_model("design"),
            timeout_s=enrich_timeout_s("design")))
        return {"repo_slug": slug, "narratives": narratives,
                "token_usage": dict(runner.token_usage)}

    return _start_or_reuse_enrich(wid, slug, "design", compute, refresh, neo4j)


@router.get("/workspaces/{wid}/design/enrichment")
def design_enrichment(wid: str, session: Session = Depends(get_session),
                      neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    return _enrichment_view(wid, ws.repo_slug, "design", neo4j)


class _DomainRefineBody(BaseModel):
    instruction: str = ""


def _brd_text(neo, slug: str) -> str:
    """Latest BRD as plain text for the decomposition prompt; '' if none yet."""
    try:
        latest = BRDStorage(neo).get_latest(slug)
    except _NEO4J_ERRORS:
        return ""
    if not latest:
        return ""
    import json as _json
    secs = latest.get("sections")
    if secs:
        try:
            return "\n\n".join(s.get("body_markdown", "")
                               for s in _json.loads(secs) if isinstance(s, dict))
        except Exception:  # noqa: BLE001
            pass
    return str(latest.get("html", ""))


def _backlog_json_for_domain(neo, slug: str) -> str:
    """The persisted backlog's stories as a compact JSON string for the decomposition
    prompt, or '' when no backlog exists (domain then grounds on the BRD alone). Never
    raises — story injection is best-effort context, not a hard dependency."""
    try:
        from cobol_modernizer.backlog.storage import BacklogStorage
        import json as _json
        latest = BacklogStorage(neo).get_latest(slug)
        if not latest:
            return ""
        return _json.dumps({
            "epics": _json.loads(latest.get("epics_json") or "[]"),
            "stories": _json.loads(latest.get("stories_json") or "[]"),
        })
    except Exception:  # noqa: BLE001 — story injection is best-effort, never fatal to domain run
        logger.warning("could not read backlog for domain %s — proceeding without it", slug, exc_info=True)
        return ""


def _domain_run_and_persist(slug: str, *, wid: str | None = None,
                            instruction: str = "") -> dict:
    neo = jobs.make_neo4j()
    s = jobs.make_session() if wid else None
    try:
        brd = _brd_text(neo, slug)
        if instruction:
            brd = f"{brd}\n\n## Refinement instruction\n{instruction}"
        runner = SdkAgentRunner()
        ledger = PgRepo(s) if s is not None else None
        run = None
        if ledger is not None and wid is not None:
            run = ledger.start_run(workspace_id=wid, stage_id=None, role="domain-design",
                                   model=enrich_model("domain"), started_by="system")
            s.flush()
        backlog_json = _backlog_json_for_domain(neo, slug)
        dd = run_domain_design(neo, slug, brd_text=brd, runner=runner,
                               model=enrich_model("domain"),
                               # decomposition over the BRD + graph summary is heavier than
                               # a narrative enrich; give it real headroom (override via
                               # DOMAIN_ENRICH_TIMEOUT_S).
                               timeout_s=enrich_timeout_s("domain", default=300.0),
                               backlog_json=backlog_json,
                               ledger=ledger, workspace_id=wid,
                               agent_run_id=run.id if run is not None else None)
        neo.run("MERGE (r:Repository {slug:$slug})", slug=slug)
        dd = DomainDesignStorage(neo).save(dd, html=render_html(dd),
                                           model=enrich_model("domain"),
                                           token_usage=dict(runner.token_usage),
                                           evidence_map={})
        known_refs = _known_refs(neo, slug)
        quality_passed, quality_result, quality_threshold = assess_domain_quality(
            dd, known_refs=known_refs, backlog_json=backlog_json)
        if s is not None and wid:
            upsert_gate(s, wid, "domain", "domain_quality",
                        passed=quality_passed, result=quality_result,
                        threshold=quality_threshold)
        stage_status = "done" if quality_passed else "incomplete"
        if wid:
            # Light the "domain" journey node green (best-effort; no-op if the row
            # isn't seeded, e.g. a workspace created before this stage existed).
            try:
                blocked = bool(ledger and _has_blocking_work_units(
                    ledger, workspace_id=wid, stage="domain-design"))
                stage_status = "incomplete" if blocked or not quality_passed else "done"
                if blocked or not quality_passed:
                    _mark_stage_status(s, wid, "domain", "incomplete")
                else:
                    _mark_passed(s, wid, "domain")
                s.commit()
            except Exception:  # noqa: BLE001 — stage marking must never fail the job
                s.rollback()
        if s is not None:
            s.commit()
        work_units = _work_unit_progress(s, wid, "domain-design") if s is not None and wid else None
        return {"repo_slug": slug, "version": dd.version, "rating": dd.rating,
                "contexts": [c.model_dump(mode="json") for c in dd.contexts],
                "designs": [d.model_dump(mode="json") for d in dd.designs],
                "token_usage": dict(runner.token_usage),
                "quality": quality_result, "quality_passed": quality_passed,
                "quality_threshold": quality_threshold,
                "work_units": work_units, "stage_status": stage_status,
                "_job_status": stage_status}
    finally:
        if s is not None:
            s.close()
        try:
            neo.close()
        except Exception:  # noqa: BLE001
            pass


@router.post("/workspaces/{wid}/domain-design", status_code=202)
def domain_design_start(wid: str, session: Session = Depends(get_session),
                        neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    slug = ws.repo_slug
    return _job_view(jobs.runner.start("domain-design", wid,
                                       lambda: _domain_run_and_persist(slug, wid=wid)))


@router.post("/workspaces/{wid}/domain-design/refine", status_code=202)
def domain_design_refine(wid: str, body: _DomainRefineBody,
                         session: Session = Depends(get_session),
                         neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    instruction = (body.instruction or "").strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction must be non-empty")
    _require_llm()
    slug = ws.repo_slug
    return _job_view(jobs.runner.start("domain-design", wid,
                                       lambda: _domain_run_and_persist(slug, wid=wid, instruction=instruction)))


@router.get("/workspaces/{wid}/domain-design")
def domain_design_status(wid: str, session: Session = Depends(get_session),
                         neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    job = jobs.runner.get("domain-design", wid)
    if job is not None:
        view = _job_view(job)
        view["work_units"] = _work_unit_progress(session, wid, "domain-design")
        if view.get("result") and "quality" not in view["result"]:
            view["result"].update(_domain_quality_response(session, wid))
        return view
    try:
        latest = DomainDesignStorage(neo4j).get_latest(ws.repo_slug)
    except _NEO4J_ERRORS:
        latest = None
    if latest:
        import json as _json
        status = "incomplete" if _stage_status(session, wid, "domain") == "incomplete" else "done"
        result = {
            "repo_slug": ws.repo_slug, "version": latest.get("version"),
            "rating": latest.get("rating"),
            "contexts": _json.loads(latest.get("contexts_json") or "[]"),
            "designs": _json.loads(latest.get("designs_json") or "[]"),
            "stage_status": status}
        result.update(_domain_quality_response(session, wid))
        return {"status": status, "error": None, "result": result,
            "work_units": _work_unit_progress(session, wid, "domain-design")}
    return {"status": "idle", "result": None, "error": None,
            "work_units": _work_unit_progress(session, wid, "domain-design")}


@router.get("/workspaces/{wid}/domain-design/html", response_class=HTMLResponse)
def domain_design_html(wid: str, session: Session = Depends(get_session),
                       neo4j=Depends(get_neo4j)) -> HTMLResponse:
    ws = _workspace(session, wid)
    try:
        latest = DomainDesignStorage(neo4j).get_latest(ws.repo_slug)
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")
    if not latest or not latest.get("html"):
        raise HTTPException(status_code=404, detail="no domain design yet — run it first")
    return HTMLResponse(content=latest["html"])
