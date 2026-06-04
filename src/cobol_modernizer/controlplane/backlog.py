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

from cobol_modernizer.agent.context_pack import (
    build_context_pack,
    build_backlog_epics_pack,
    build_backlog_oneshot_pack,
    build_backlog_stories_pack,
)
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from neo4j.exceptions import DriverError, Neo4jError
from sqlalchemy.orm import Session

from cobol_modernizer.agent.harness import SdkAgentRunner
from cobol_modernizer.backlog.dependency import derive_story_dependencies
from cobol_modernizer.backlog.generator import (
    COVERAGE_TOPUP_EPIC_ID,
    _covered_requirements,
    _decompose,
    _env_float,
    _env_int,
    _generate_backlog_oneshot,
    _requirement_ids_of_sections,
    _scope_epic_refs,
    _sections_for_requirements,
    generate_deterministic_backlog,
    generate_epics,
    generate_backlog_result,
    generate_stories_for_epic,
    parse_backlog_payload,
)
from cobol_modernizer.backlog.readiness import assess_backlog_readiness
from cobol_modernizer.backlog.render import render_html
from cobol_modernizer.backlog.storage import BacklogStorage
from cobol_modernizer.brd.storage import BRDStorage
from cobol_modernizer.controlplane import jobs
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.controlplane.gates_util import upsert_gate
from cobol_modernizer.enrichment.base import EnrichmentResult
from cobol_modernizer.enrichment.refs import relevant_refs
from cobol_modernizer.persistence.repo import PgRepo
from cobol_modernizer.persistence.tables import Workspace
from cobol_modernizer.seam.service import rank_candidates
from cobol_modernizer.traceability.coverage import brd_logic_coverage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["controlplane-backlog"])
_NEO4J_ERRORS = (Neo4jError, DriverError)

_GRAPH_REFS_Q = "MATCH (n:CodeEntity {repo:$repo}) RETURN n.qualified_name AS q"
_DEFAULT_MODEL = "claude-sonnet-4-6"
_REAL_GENERATE_BACKLOG_RESULT = generate_backlog_result


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


def _pack_for_backlog_oneshot(*, brd_sections: list[dict], known_refs: list[str],
                              brd_evidence_map: dict, known_requirement_ids: list[str]):
    return build_backlog_oneshot_pack(
        brd_sections=brd_sections, known_refs=known_refs,
        brd_evidence_map=brd_evidence_map,
        known_requirement_ids=known_requirement_ids,
        relevant_refs_fn=relevant_refs)


def _pack_for_epics_unit(*, brd_sections: list[dict], known_refs: list[str],
                         brd_evidence_map: dict, known_requirement_ids: list[str]):
    return build_backlog_epics_pack(
        brd_sections=brd_sections, known_refs=known_refs,
        brd_evidence_map=brd_evidence_map,
        known_requirement_ids=known_requirement_ids,
        relevant_refs_fn=relevant_refs)


def _pack_for_stories_unit(*, epic: dict, req_ids: set[str],
                           brd_sections: list[dict], known_refs: list[str],
                           brd_evidence_map: dict, brd_relevant: list[str],
                           known_requirement_ids: list[str], round_key: str):
    sections_for_epic = _sections_for_requirements(brd_sections, req_ids)
    if not sections_for_epic:
        sections_for_epic = brd_sections
    refs = _scope_epic_refs(req_ids, brd_evidence_map, known_refs, brd_relevant)
    return build_backlog_stories_pack(
        epic=epic, req_ids=req_ids,
        brd_sections_for_epic=sections_for_epic, refs=refs,
        known_requirement_ids=known_requirement_ids, round_key=round_key)


def _use_deterministic_backlog() -> bool:
    mode = os.environ.get("BACKLOG_GEN_MODE", "auto").strip().lower()
    if mode in {"decomposed", "oneshot", "llm"}:
        return False
    if mode in {"deterministic", "fast"}:
        return True
    flag = os.environ.get("BACKLOG_DETERMINISTIC_FIRST", "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def _pack_for_deterministic_backlog(*, brd_sections: list[dict], known_refs: list[str],
                                    brd_evidence_map: dict,
                                    known_requirement_ids: list[str]):
    brd_relevant = relevant_refs(brd_evidence_map, known_refs) or list(known_refs)
    return build_context_pack(
        stage="backlog", unit_type="deterministic", unit_key="backlog",
        sections=[
            {"title": "BRD sections", "content": brd_sections},
            {"title": "BRD evidence map", "content": brd_evidence_map,
             "required": False},
            {"title": "Known requirement ids", "content": known_requirement_ids},
        ],
        refs=brd_relevant,
        prompt_version="backlog-deterministic-v1")


async def _generate_backlog_with_ledger(
    *, runner, model: str, timeout_s: float, max_turns: int,
    brd_sections: list[dict], known_refs: list[str],
    brd_evidence_map: dict[str, list[str]], known_requirement_ids: list[str],
    ledger: PgRepo, workspace_id: str, repo_slug: str, agent_run_id: str | None,
) -> EnrichmentResult:
    brd_relevant = relevant_refs(brd_evidence_map, known_refs) or list(known_refs)
    unit_attempts = max(1, _env_int("BACKLOG_UNIT_ATTEMPTS", 2))

    if _use_deterministic_backlog():
        pack = _pack_for_deterministic_backlog(
            brd_sections=brd_sections, known_refs=known_refs,
            brd_evidence_map=brd_evidence_map,
            known_requirement_ids=known_requirement_ids)
        cached = ledger.find_cached_work_unit(
            workspace_id=workspace_id, stage="backlog",
            unit_type="deterministic", unit_key="backlog",
            input_hash=pack.input_hash)
        if cached is not None:
            return EnrichmentResult(payload=cached.payload, ok=True, cause=None)
        unit = ledger.create_work_unit(
            workspace_id=workspace_id, repo_slug=repo_slug, stage="backlog",
            unit_type="deterministic", unit_key="backlog",
            input_hash=pack.input_hash, agent_run_id=agent_run_id,
            model="deterministic", timeout_s=0.0, max_turns=0)
        ledger.mark_work_unit_running(
            unit.id, model="deterministic", timeout_s=0.0, max_turns=0)
        payload = generate_deterministic_backlog(
            brd_sections=brd_sections, known_refs=known_refs,
            known_requirement_ids=known_requirement_ids,
            brd_evidence_map=brd_evidence_map)
        if payload.get("stories"):
            ledger.mark_work_unit_succeeded(
                unit.id, payload=payload,
                token_usage={"input": 0, "output": 0, "cache_read": 0,
                             "cache_creation": 0},
                cost_usd=0.0)
            logger.info("backlog: deterministic generation produced %d epics and "
                        "%d stories for %s", len(payload.get("epics", [])),
                        len(payload.get("stories", [])), repo_slug)
            return EnrichmentResult(payload=payload, ok=True, cause=None)
        ledger.mark_work_unit_failed(
            unit.id, error_cause="deterministic generation produced no stories")
        if os.environ.get("BACKLOG_GEN_MODE", "auto").strip().lower() in {
            "deterministic", "fast",
        }:
            return EnrichmentResult(
                payload={}, ok=False,
                cause="deterministic generation produced no stories")
        logger.warning("backlog: deterministic generation produced no stories for "
                       "%s; falling back to LLM path", repo_slug)

    if not _decompose(brd_sections, known_requirement_ids):
        pack = _pack_for_backlog_oneshot(
            brd_sections=brd_sections, known_refs=known_refs,
            brd_evidence_map=brd_evidence_map,
            known_requirement_ids=known_requirement_ids)
        cached = ledger.find_cached_work_unit(
            workspace_id=workspace_id, stage="backlog", unit_type="oneshot",
            unit_key="backlog", input_hash=pack.input_hash)
        if cached is not None:
            return EnrichmentResult(payload=cached.payload, ok=True, cause=None)
        unit = ledger.create_work_unit(
            workspace_id=workspace_id, repo_slug=repo_slug, stage="backlog",
            unit_type="oneshot", unit_key="backlog", input_hash=pack.input_hash,
            agent_run_id=agent_run_id, model=model, timeout_s=timeout_s,
            max_turns=max_turns)
        ledger.mark_work_unit_running(
            unit.id, model=model, timeout_s=timeout_s, max_turns=max_turns)
        result = await _generate_backlog_oneshot(
            runner=runner, model=model, timeout_s=timeout_s,
            brd_sections=brd_sections, relevant_refs=brd_relevant,
            known_requirement_ids=known_requirement_ids, max_turns=max_turns)
        if not result.ok or not result.payload:
            ledger.mark_work_unit_failed(unit.id, error_cause=result.cause or "no output")
            return result
        ledger.mark_work_unit_succeeded(
            unit.id, payload=result.payload,
            token_usage=dict(getattr(runner, "token_usage", {}) or {}),
            cost_usd=float(getattr(runner, "cost_usd", 0.0) or 0.0))
        return result

    epic_timeout_s = _env_float("BACKLOG_EPIC_TIMEOUT_S", 120.0)
    story_timeout_s = _env_float("BACKLOG_STORY_TIMEOUT_S", 120.0)
    story_max_turns = _env_int("BACKLOG_STORY_MAX_TURNS", 6)
    max_concurrency = max(1, _env_int("BACKLOG_MAX_CONCURRENCY", 4))
    max_rounds = max(1, _env_int("BACKLOG_MAX_ROUNDS", 100))
    no_progress_limit = max(1, _env_int("BACKLOG_NO_PROGRESS_ROUNDS", 2))
    semaphore = asyncio.Semaphore(max_concurrency)

    epics_pack = _pack_for_epics_unit(
        brd_sections=brd_sections, known_refs=known_refs,
        brd_evidence_map=brd_evidence_map,
        known_requirement_ids=known_requirement_ids)
    cached_epics = ledger.find_cached_work_unit(
        workspace_id=workspace_id, stage="backlog", unit_type="epics",
        unit_key="epics", input_hash=epics_pack.input_hash)
    if cached_epics is not None:
        epics = [e for e in cached_epics.payload.get("epics", []) if isinstance(e, dict)]
        epics_unit_id = cached_epics.id
    else:
        epics_unit = ledger.create_work_unit(
            workspace_id=workspace_id, repo_slug=repo_slug, stage="backlog",
            unit_type="epics", unit_key="epics", input_hash=epics_pack.input_hash,
            agent_run_id=agent_run_id, model=model, timeout_s=epic_timeout_s,
            max_turns=max_turns)
        epics_unit_id = epics_unit.id
        ledger.mark_work_unit_running(
            epics_unit.id, model=model, timeout_s=epic_timeout_s,
            max_turns=max_turns)
        epics_res = await generate_epics(
            runner=runner, model=model, timeout_s=epic_timeout_s,
            max_turns=max_turns, brd_sections=brd_sections,
            relevant_refs=brd_relevant,
            known_requirement_ids=known_requirement_ids,
            attempts=unit_attempts, escalate=True)
        epics = [e for e in epics_res.payload.get("epics", []) if isinstance(e, dict)]
        if not epics_res.ok or not epics:
            cause = epics_res.cause or "no epics"
            ledger.mark_work_unit_failed(
                epics_unit.id, error_cause=f"epics generation failed: {cause}")
            return EnrichmentResult(
                payload={}, ok=False, cause=f"epics generation failed: {cause}")
        ledger.mark_work_unit_succeeded(
            epics_unit.id, payload={"epics": epics},
            token_usage=dict(getattr(runner, "token_usage", {}) or {}),
            cost_usd=float(getattr(runner, "cost_usd", 0.0) or 0.0))

    async def _stories_unit(epic: dict, req_ids: set[str], round_key: str) -> list[dict]:
        epic_id = str(epic.get("id", ""))
        pack = _pack_for_stories_unit(
            epic=epic, req_ids=req_ids, brd_sections=brd_sections,
            known_refs=known_refs, brd_evidence_map=brd_evidence_map,
            brd_relevant=brd_relevant,
            known_requirement_ids=known_requirement_ids, round_key=round_key)
        cached = ledger.find_cached_work_unit(
            workspace_id=workspace_id, stage="backlog", unit_type="stories",
            unit_key=pack.unit_key, input_hash=pack.input_hash)
        if cached is not None:
            return [s for s in cached.payload.get("stories", []) if isinstance(s, dict)]
        unit = ledger.create_work_unit(
            workspace_id=workspace_id, repo_slug=repo_slug, stage="backlog",
            unit_type="stories", unit_key=pack.unit_key, input_hash=pack.input_hash,
            agent_run_id=agent_run_id, parent_unit_ids=[epics_unit_id],
            model=model, timeout_s=story_timeout_s, max_turns=story_max_turns)
        ledger.mark_work_unit_running(
            unit.id, model=model, timeout_s=story_timeout_s,
            max_turns=story_max_turns)
        sections_for_epic = _sections_for_requirements(brd_sections, req_ids)
        if not sections_for_epic:
            sections_for_epic = brd_sections
        refs = list(pack.refs)
        async with semaphore:
            res = await generate_stories_for_epic(
                runner=runner, model=model, timeout_s=story_timeout_s,
                max_turns=story_max_turns, epic=epic,
                brd_sections_for_epic=sections_for_epic,
                relevant_refs=refs,
                known_requirement_ids=known_requirement_ids,
                attempts=unit_attempts, escalate=True)
        if not res.ok:
            ledger.mark_work_unit_failed(unit.id, error_cause=res.cause or "no output")
            logger.warning("backlog: stories unit for epic %s failed (%s)",
                           epic_id, res.cause)
            return []
        stories = [s for s in res.payload.get("stories", []) if isinstance(s, dict)]
        ledger.mark_work_unit_succeeded(
            unit.id, payload={"stories": stories},
            token_usage=dict(getattr(runner, "token_usage", {}) or {}),
            cost_usd=float(getattr(runner, "cost_usd", 0.0) or 0.0))
        return stories

    initial = await asyncio.gather(*[
        _stories_unit(epic, set(epic.get("brd_requirement_ids", []) or []), "initial")
        for epic in epics
    ])
    all_stories = [story for group in initial for story in group]
    if not all_stories:
        return EnrichmentResult(
            payload={}, ok=False,
            cause="stories generation failed: no stories produced for any epic")

    all_req_ids = set(known_requirement_ids) or set(_requirement_ids_of_sections(brd_sections))
    epics_by_id = {str(e.get("id", "")): e for e in epics}
    topup_round = 0
    no_progress_streak = 0
    while topup_round < max_rounds:
        covered = _covered_requirements(all_stories)
        uncovered = all_req_ids - covered
        if not uncovered:
            break
        units: dict[str, tuple[dict, set[str]]] = {}
        orphans: set[str] = set()
        for rid in uncovered:
            owner = next((e for e in epics
                          if rid in (e.get("brd_requirement_ids") or [])), None)
            if owner is None:
                orphans.add(rid)
                continue
            eid = str(owner.get("id", ""))
            units.setdefault(eid, (owner, set()))[1].add(rid)
        if orphans:
            topup = epics_by_id.get(COVERAGE_TOPUP_EPIC_ID)
            if topup is None:
                topup = {"id": COVERAGE_TOPUP_EPIC_ID,
                         "title": "Coverage top-up",
                         "outcome": "Cover BRD requirements not owned by any epic.",
                         "brd_requirement_ids": sorted(orphans),
                         "evidence_refs": []}
                epics.append(topup)
                epics_by_id[COVERAGE_TOPUP_EPIC_ID] = topup
            else:
                topup["brd_requirement_ids"] = sorted(
                    set(topup.get("brd_requirement_ids", [])) | orphans)
            units[COVERAGE_TOPUP_EPIC_ID] = (topup, set(orphans))

        round_key = f"topup-{topup_round + 1}"
        groups = await asyncio.gather(*[
            _stories_unit(epic, req_ids, round_key)
            for epic, req_ids in units.values()
        ])
        new_stories = [story for group in groups for story in group]
        topup_round += 1
        newly_covered = _covered_requirements(new_stories) & uncovered
        all_stories.extend(new_stories)
        if newly_covered:
            no_progress_streak = 0
        else:
            no_progress_streak += 1
        logger.info("backlog: ledger top-up round %d — %d uncovered before, "
                    "%d newly covered (no-progress streak %d/%d)", topup_round,
                    len(uncovered), len(newly_covered), no_progress_streak,
                    no_progress_limit)
        if no_progress_streak >= no_progress_limit:
            break

    return EnrichmentResult(payload={"epics": epics, "stories": all_stories},
                            ok=True, cause=None)


def run_backlog(*, session: Session, neo4j, workspace: Workspace,
                generate: Callable[..., Any] | None = None) -> dict:
    """Generate + persist a backlog and publish its gates. `generate` is the TYPED
    orchestrator returning an `EnrichmentResult` (defaults to `generate_backlog_result`;
    injected by tests)."""
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
    # The graph grounding lives in the BRD's SEPARATE evidence_map (requirement_id ->
    # [qualified_names]), persisted as a JSON string like `sections` — the sections
    # themselves carry no refs. Parse it defensively; legacy/missing -> {} (the
    # generator then falls back to inlining ALL known_refs, never 0).
    raw_em = brd.get("evidence_map")
    if isinstance(raw_em, str):
        try:
            brd_evidence_map = json.loads(raw_em or "{}")
        except json.JSONDecodeError:
            logger.warning("backlog: malformed BRD evidence_map JSON for %s — treating as empty", slug)
            brd_evidence_map = {}
    else:
        brd_evidence_map = raw_em or {}
    if not isinstance(brd_evidence_map, dict):
        brd_evidence_map = {}
    known_refs = [r["q"] for r in neo4j.run(_GRAPH_REFS_Q, repo=slug) if r.get("q")]
    known_req_ids = _requirement_ids(sections)

    # The relevance scoper inlines only the BRD-evidence-map-relevant refs into the
    # prompt (lossless relevance, NO cap): the full graph (thousands of refs) blows
    # the prompt budget. Scoping is now driven by the evidence_map (NOT the section
    # text, which has no refs — the old bug that inlined 0 refs). The generator does
    # the per-epic scoping + the all-known_refs fallback. The FULL `known_refs` is
    # still passed for prompt scoping AND used for grounding below.
    relevant = relevant_refs(brd_evidence_map, known_refs) or known_refs
    logger.info("backlog: %d known graph refs, %d BRD-evidence-map-relevant refs to "
                "inline into prompt for %s", len(known_refs), len(relevant), slug)

    # Ensure a :Repository node exists for BacklogStorage (mirrors blueprint.py MERGE).
    neo4j.run("MERGE (r:Repository {slug: $slug}) SET r.name = coalesce(r.name, $slug)",
              slug=slug)

    gen = generate or generate_backlog_result
    use_ledger = generate is None and gen is _REAL_GENERATE_BACKLOG_RESULT
    runner = SdkAgentRunner()
    # NO OUTER WALL: the orchestrator is run to completion (plain `asyncio.run`, NO
    # `asyncio.wait_for` around it) so a single BACKLOG_TIMEOUT_S=300 wall can't kill
    # the whole uncapped multi-round completeness loop mid-coverage at the old 300s
    # cliff. BACKLOG_TIMEOUT_S is passed DOWN only as the per-unit one-shot `timeout_s`
    # budget; the decomposed path's per-unit budgets (BACKLOG_EPIC/STORY_TIMEOUT_S, now
    # retried-with-escalation) bound the work, and the JobRunner lets a long job run.
    model = os.environ.get("BACKLOG_MODEL", _DEFAULT_MODEL)
    timeout_s = float(os.environ.get("BACKLOG_TIMEOUT_S", "300"))
    max_turns = int(os.environ.get("BACKLOG_MAX_TURNS", "6"))
    if use_ledger:
        ledger = PgRepo(session)
        agent_run = ledger.start_run(
            workspace_id=workspace.id, stage_id=None, role="backlog",
            model=model, started_by="system")
        session.flush()
        result: EnrichmentResult = asyncio.run(
            _generate_backlog_with_ledger(
                runner=runner, model=model, timeout_s=timeout_s,
                max_turns=max_turns, brd_sections=sections,
                known_refs=known_refs, brd_evidence_map=brd_evidence_map,
                known_requirement_ids=sorted(known_req_ids), ledger=ledger,
                workspace_id=workspace.id, repo_slug=slug,
                agent_run_id=agent_run.id))
    else:
        result = asyncio.run(
            gen(runner=runner, model=model, timeout_s=timeout_s,
                max_turns=max_turns, brd_sections=sections, known_refs=known_refs,
                brd_evidence_map=brd_evidence_map,
                known_requirement_ids=sorted(known_req_ids)))
    if not result.ok or not result.payload:
        # The orchestrator swallows an LLM error/timeout/turn-cap/empty-output into a
        # typed failure. Fail the job loudly rather than persist an empty backlog and
        # report success — and surface the orchestrator's CONCRETE cause (e.g. "epics
        # generation failed: timeout", "no output (turn cap / parse / api error)") so
        # the 502 names WHICH failure it was. (ok=True with an empty payload shouldn't
        # happen, but is defensively treated as a failure too.)
        cause = result.cause or "no output"
        raise HTTPException(status_code=502, detail=f"backlog generation failed: {cause}")
    raw = result.payload
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

    # The orchestrator may return ok=True with some BRD requirements still uncovered
    # (it stopped at BACKLOG_MAX_ROUNDS). The brd_logic_coverage gate below already
    # computes/surfaces that and gates on BACKLOG_COVERAGE_MIN — no extra logic here.
    report = brd_logic_coverage(neo4j, slug, sections, backlog.evidence_map)
    logger.info("backlog: coverage ratio %.3f for %s", report.coverage_ratio, slug)
    coverage = report.model_dump(mode="json")
    BacklogStorage(neo4j).save(backlog, coverage=coverage,
                               html=render_html(backlog, coverage))

    min_cov = _coverage_min()
    passed = report.coverage_ratio >= min_cov
    threshold = {"min_coverage": min_cov}
    gate_result = {"coverage_ratio": report.coverage_ratio, "uncovered": report.uncovered_refs[:50]}
    upsert_gate(session, workspace.id, "backlog", "backlog_coverage",
                passed=passed, result=gate_result, threshold=threshold)
    upsert_gate(session, workspace.id, "blueprint", "brd_logic_coverage",
                passed=passed, result=gate_result, threshold=threshold)
    ready, ready_result, ready_threshold = assess_backlog_readiness(
        backlog, brd_sections=sections, known_refs=set(known_refs),
        graph_coverage_ratio=report.coverage_ratio, min_graph_coverage=min_cov)
    upsert_gate(session, workspace.id, "backlog", "backlog_readiness",
                passed=ready, result=ready_result, threshold=ready_threshold)
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
