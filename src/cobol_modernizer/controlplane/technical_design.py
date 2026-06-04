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

from cobol_modernizer.agent.context_pack import build_technical_service_pack
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from neo4j.exceptions import DriverError, Neo4jError
from sqlalchemy import select
from sqlalchemy.orm import Session

from cobol_modernizer.agent.harness import SdkAgentRunner
from cobol_modernizer.backlog.storage import BacklogStorage
from cobol_modernizer.controlplane import jobs
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.controlplane.domain import DomainDesignStorage
from cobol_modernizer.controlplane.gates_util import upsert_gate
from cobol_modernizer.enrichment.base import EnrichmentResult
from cobol_modernizer.persistence.tables import Gate, Workspace
from cobol_modernizer.persistence.repo import PgRepo
from cobol_modernizer.seam.service import rank_candidates
from cobol_modernizer.technical_design.generator import (
    enrich_technical_design_metadata,
    fallback_technical_design_payload,
    generate_service_for_context,
    generate_technical_design_result,
    parse_technical_design_payload,
)
from cobol_modernizer.enrichment.refs import relevant_refs
from cobol_modernizer.technical_design.quality import assess_technical_design_quality
from cobol_modernizer.technical_design.render import render_html
from cobol_modernizer.technical_design.storage import TechnicalDesignStorage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["controlplane-technical-design"])
_NEO4J_ERRORS = (Neo4jError, DriverError)
_GRAPH_REFS_Q = "MATCH (n:CodeEntity {repo:$repo}) RETURN n.qualified_name AS q"
_DEFAULT_MODEL = "claude-sonnet-4-6"
_REAL_GENERATE_TECHNICAL_DESIGN_RESULT = generate_technical_design_result


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


def _technical_design_stage_status(session: Session, workspace_id: str) -> str:
    blocking = session.execute(
        select(Gate).where(
            Gate.workspace_id == workspace_id,
            Gate.gate_key.in_({
                "design_generation_complete",
                "design_data_ownership",
                "technical_design_quality",
            }),
            Gate.status == "open",
        )
    ).scalars().first()
    return "incomplete" if blocking is not None else "done"


def _use_deterministic_technical_design() -> bool:
    mode = os.environ.get("TECHNICAL_DESIGN_MODE", "").strip().lower()
    if mode in {"llm", "agent"}:
        return False
    if mode in {"deterministic", "fast", ""}:
        return True
    legacy = os.environ.get("TECH_DESIGN_GEN_MODE", "").strip().lower()
    return legacy not in {"llm", "agent", "oneshot", "decomposed"}


def _gate_view(session: Session, workspace_id: str, gate_key: str) -> dict | None:
    gate = session.execute(
        select(Gate).where(Gate.workspace_id == workspace_id, Gate.gate_key == gate_key)
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


def _technical_quality_response(session: Session, workspace_id: str) -> dict:
    gate = _gate_view(session, workspace_id, "technical_design_quality")
    return {
        "quality_gate": gate,
        "quality": gate["result"] if gate else None,
        "quality_threshold": gate["threshold"] if gate else None,
        "quality_passed": (gate["status"] == "passed") if gate else None,
    }


def _pack_for_service_unit(*, context: dict, stories: list[dict], seam_waves: list,
                           known_refs: list[str], known_story_ids: list[str]):
    return build_technical_service_pack(
        context=context, stories=stories, seam_waves=seam_waves,
        known_refs=known_refs, known_story_ids=known_story_ids,
        relevant_refs_fn=relevant_refs)


async def _generate_technical_design_with_ledger(
    *, runner, model: str, timeout_s: float, max_turns: int,
    contexts: list[dict], stories: list[dict], seam_waves: list,
    known_refs: list[str], known_story_ids: list[str], ledger: PgRepo,
    workspace_id: str, repo_slug: str, agent_run_id: str | None,
) -> EnrichmentResult:
    named = [c for c in contexts if isinstance(c, dict) and c.get("name")]
    if not named:
        return EnrichmentResult(payload={}, ok=False, cause="no bounded contexts")

    backlog_json = json.dumps({"stories": stories})
    seam_waves_json = json.dumps(seam_waves)
    ctx_timeout_s = float(os.environ.get("TECH_DESIGN_CONTEXT_TIMEOUT_S", str(timeout_s)))
    ctx_max_turns = int(os.environ.get("TECH_DESIGN_CONTEXT_MAX_TURNS", str(max_turns)))
    unit_attempts = max(1, int(os.environ.get("TECH_DESIGN_UNIT_ATTEMPTS", "2")))
    max_concurrency = max(1, int(os.environ.get("TECH_DESIGN_MAX_CONCURRENCY", "4")))
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _one(context: dict) -> list[dict]:
        ctx_name = str(context.get("name", ""))
        pack = _pack_for_service_unit(
            context=context, stories=stories, seam_waves=seam_waves,
            known_refs=known_refs, known_story_ids=known_story_ids)
        cached = ledger.find_cached_work_unit(
            workspace_id=workspace_id, stage="technical-design",
            unit_type="service", unit_key=ctx_name, input_hash=pack.input_hash)
        if cached is not None:
            return [s for s in cached.payload.get("services", []) if isinstance(s, dict)]

        unit = ledger.create_work_unit(
            workspace_id=workspace_id, repo_slug=repo_slug, stage="technical-design",
            unit_type="service", unit_key=ctx_name, input_hash=pack.input_hash,
            agent_run_id=agent_run_id, model=model, timeout_s=ctx_timeout_s,
            max_turns=ctx_max_turns)
        ledger.mark_work_unit_running(
            unit.id, model=model, timeout_s=ctx_timeout_s, max_turns=ctx_max_turns)
        refs = list(pack.refs)
        try:
            async with semaphore:
                result = await generate_service_for_context(
                    runner=runner, model=model, timeout_s=ctx_timeout_s,
                    max_turns=ctx_max_turns, context=context,
                    backlog_json=backlog_json, seam_waves_json=seam_waves_json,
                    relevant_refs=refs, known_story_ids=known_story_ids,
                    attempts=unit_attempts, escalate=True)
        except Exception as exc:
            ledger.mark_work_unit_failed(unit.id, error_cause=f"{type(exc).__name__}: {exc}")
            raise
        if not result.ok:
            ledger.mark_work_unit_failed(unit.id, error_cause=result.cause or "no output")
            logger.warning("technical-design: service unit for %s failed (%s)",
                           ctx_name, result.cause)
            return []
        payload = {"services": [s for s in result.payload.get("services", [])
                                if isinstance(s, dict)]}
        ledger.mark_work_unit_succeeded(
            unit.id, payload=payload,
            token_usage=dict(getattr(runner, "token_usage", {}) or {}),
            cost_usd=float(getattr(runner, "cost_usd", 0.0) or 0.0))
        return payload["services"]

    results = await asyncio.gather(*[_one(c) for c in named])
    services = [svc for group in results for svc in group]
    if not services:
        return EnrichmentResult(
            payload={}, ok=False,
            cause="no output (turn cap / parse / api error): no service produced for "
                  "any bounded context")
    return EnrichmentResult(payload={"services": services}, ok=True, cause=None)


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

    # The typed orchestrator scopes each context to its OWN lossless-relevant refs
    # (NO truncation — the legacy 200-ref prompt cap is gone). We pass the FULL
    # `known_refs` so it can compute per-context relevance and so grounding in
    # `parse_technical_design_payload` below sees every known ref.
    #
    # NO single outer 300s wall: `timeout_s` here is the PER-CONTEXT budget (the
    # decomposed path uses it only as the default for TECH_DESIGN_CONTEXT_TIMEOUT_S,
    # and each unit retries with escalation TECH_DESIGN_UNIT_ATTEMPTS times). It does
    # NOT cap the whole multi-context orchestration — the orchestrator never wraps its
    # fan-out gather in a single asyncio wall, and the JobRunner lets the long job run
    # to completion, so a slow-but-progressing design is never killed mid-flight. We
    # read TECH_DESIGN_CONTEXT_TIMEOUT_S first (falling back to the legacy
    # TECHNICAL_DESIGN_TIMEOUT_S, then 300s) so the knob name reflects the new
    # per-context contract.
    per_context_timeout_s = float(
        os.environ.get("TECH_DESIGN_CONTEXT_TIMEOUT_S")
        or os.environ.get("TECHNICAL_DESIGN_TIMEOUT_S", "300"))
    gen = generate or generate_technical_design_result
    use_real_generator = generate is None and gen is _REAL_GENERATE_TECHNICAL_DESIGN_RESULT
    use_deterministic = use_real_generator and _use_deterministic_technical_design()
    use_ledger = use_real_generator and not use_deterministic
    runner = SdkAgentRunner()
    agent_run = None
    if use_deterministic:
        raw = fallback_technical_design_payload(
            contexts=contexts, stories=stories, seam_waves=seam_waves,
            known_refs=known_refs)
        result = EnrichmentResult(payload=raw, ok=True, cause=None)
    elif use_ledger:
        ledger = PgRepo(session)
        agent_run = ledger.start_run(
            workspace_id=workspace.id, stage_id=None, role="technical-design",
            model=os.environ.get("TECHNICAL_DESIGN_MODEL", _DEFAULT_MODEL),
            started_by="system")
        session.flush()
        result = asyncio.run(_generate_technical_design_with_ledger(
            runner=runner,
            model=os.environ.get("TECHNICAL_DESIGN_MODEL", _DEFAULT_MODEL),
            timeout_s=per_context_timeout_s,
            max_turns=int(os.environ.get("TECHNICAL_DESIGN_MAX_TURNS", "6")),
            contexts=contexts, stories=stories, seam_waves=seam_waves,
            known_refs=sorted(known_refs), known_story_ids=sorted(known_story_ids),
            ledger=ledger, workspace_id=workspace.id, repo_slug=slug,
            agent_run_id=agent_run.id))
    else:
        result: EnrichmentResult = asyncio.run(
            gen(runner=runner,
                model=os.environ.get("TECHNICAL_DESIGN_MODEL", _DEFAULT_MODEL),
                timeout_s=per_context_timeout_s,
                max_turns=int(os.environ.get("TECHNICAL_DESIGN_MAX_TURNS", "6")),
                contexts=contexts, stories=stories, seam_waves=seam_waves,
                known_refs=sorted(known_refs), known_story_ids=sorted(known_story_ids)))
    generation_mode = "deterministic" if use_deterministic else "llm"
    generation_cause = None
    raw = result.payload
    if not result.ok or not raw:
        # The orchestrator swallows an LLM error/timeout/turn-cap/empty-output into a
        # typed failure. Surface the CONCRETE cause, then degrade to the deterministic
        # graph-grounded fallback so migration planning stays usable without another
        # model call (technical_design keeps this fallback that backlog does not).
        generation_cause = result.cause or "no output"
        logger.warning("technical_design: generation failed for %s (%s); using "
                       "deterministic fallback", slug, generation_cause)
        raw = fallback_technical_design_payload(contexts=contexts, stories=stories,
                                                seam_waves=seam_waves,
                                                known_refs=known_refs)
        generation_mode = "deterministic_fallback"
    design = parse_technical_design_payload(raw, repo_slug=slug, known_refs=known_refs,
                                            known_story_ids=known_story_ids,
                                            known_contexts=known_contexts)
    design = enrich_technical_design_metadata(design)
    TechnicalDesignStorage(neo4j).save(design, html=render_html(design))

    ok, conflicts = _data_ownership_ok(design)
    quality_passed, quality_result, quality_threshold = assess_technical_design_quality(
        design, known_contexts=known_contexts, known_story_ids=known_story_ids)
    generation_ok = generation_mode in {"deterministic", "llm"} and generation_cause is None
    upsert_gate(session, workspace.id, "design", "design_generation_complete",
                passed=generation_ok,
                result={"mode": generation_mode, "cause": generation_cause},
                threshold={"technical_design_required": True})
    upsert_gate(session, workspace.id, "design", "design_data_ownership",
                passed=ok, result={"conflicts": conflicts},
                threshold={"unique_writer_ownership": True})
    upsert_gate(session, workspace.id, "design", "technical_design_quality",
                passed=quality_passed, result=quality_result,
                threshold=quality_threshold)
    session.flush()
    stage_status = "done" if generation_ok and ok and quality_passed else "incomplete"
    return {"repo_slug": slug, "services": len(design.services),
            "data_ownership_ok": ok, "version": design.version,
            "generation_mode": generation_mode, "generation_cause": generation_cause,
            "target_platform": design.target_platform,
            "package_structure": design.package_structure,
            "database_design": design.database_design,
            "mermaid_component_diagram": design.mermaid_component_diagram,
            "quality": quality_result, "quality_passed": quality_passed,
            "quality_threshold": quality_threshold,
            "stage_status": stage_status, "_job_status": stage_status}


@router.post("/workspaces/{wid}/technical-design", status_code=202)
def technical_design_generate(wid: str, session: Session = Depends(get_session),
                              neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    if (not _use_deterministic_technical_design()
            and not os.environ.get("ANTHROPIC_API_KEY") and not jobs.runner.inline):
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
        view = _job_view(job)
        if view.get("result") and "quality" not in view["result"]:
            view["result"].update(_technical_quality_response(session, ws.id))
        return view
    try:
        latest = TechnicalDesignStorage(neo4j).get_latest(ws.repo_slug)
    except _NEO4J_ERRORS:
        latest = None
    if latest:
        status = _technical_design_stage_status(session, ws.id)
        result = {
            "repo_slug": ws.repo_slug,
            "version": latest.get("version"),
            "services": len(json.loads(latest.get("services_json") or "[]")),
            "services_detail": json.loads(latest.get("services_json") or "[]"),
            "target_platform": json.loads(latest.get("target_platform_json") or "{}"),
            "package_structure": json.loads(latest.get("package_structure_json") or "[]"),
            "database_design": json.loads(latest.get("database_design_json") or "[]"),
            "mermaid_component_diagram": latest.get("mermaid_component_diagram") or "",
            "stage_status": status,
        }
        result.update(_technical_quality_response(session, ws.id))
        return {"status": status, "error": None, "started_at": None, "finished_at": None,
                "result": result}
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
