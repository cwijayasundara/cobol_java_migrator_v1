"""Verify stage — COBOL↔Java equivalence over the deterministic equivalence engine.

POST /api/workspaces/{id}/verify diffs a candidate (generated Java) record set
against a golden master (the COBOL oracle) with COBOL-aware tolerance (COMP-3 /
zoned-overpunch scale, date formats), links every mismatch back to the source
seam via the parsed graph, and returns the verdict + seam-linked defect tickets.
Zero LLM in this path.

Golden masters aren't pre-captured for the cockpit's repos, so both record sets
are supplied in the request (honest provenance — no fabricated oracle). The
`verify` stage is marked passed only when the verdict is `pass`; a `fail` verdict
with defects marks it failed (this is a real gate, not a checkbox)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from neo4j.exceptions import DriverError, Neo4jError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from cobol_modernizer.backlog.storage import BacklogStorage
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.controlplane.gates_util import upsert_gate
from cobol_modernizer.controlplane.verify_storage import (
    latest_verify_report, record_equivalence_check, record_verify_report,
)
from cobol_modernizer.equivalence.golden import InMemoryGoldenStore
from cobol_modernizer.equivalence.lab import EquivalenceLab, split_by_subslice
from cobol_modernizer.equivalence.seam_link import resolve_source_seam
from cobol_modernizer.equivalence.tolerance import load_ruleset
from cobol_modernizer.persistence.tables import Artifact, Gate, JourneyStage, Workspace
from cobol_modernizer.slice.gates import story_behavior_gate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["controlplane-verify"])
_NEO4J_ERRORS = (Neo4jError, DriverError)

# Fan-out tuning (loop-until-done): a SOFT per-story wall + a concurrency bound.
# The timeout is soft — overrun yields a PARTIAL sub-verdict, never a hard kill.
_DEFAULT_MAX_CONCURRENCY = 4
_DEFAULT_EQUIVALENCE_TIMEOUT_S = 60.0
# Decompose-further (defect localization): bound on repeat-until-done narrowing.
_DEFAULT_MAX_REPAIR_ATTEMPTS = 2


def _max_concurrency() -> int:
    try:
        return max(1, int(os.getenv("VERIFY_MAX_CONCURRENCY", _DEFAULT_MAX_CONCURRENCY)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_CONCURRENCY


def _equivalence_timeout_s() -> float:
    try:
        return max(0.0, float(os.getenv("VERIFY_EQUIVALENCE_TIMEOUT_S",
                                        _DEFAULT_EQUIVALENCE_TIMEOUT_S)))
    except (TypeError, ValueError):
        return _DEFAULT_EQUIVALENCE_TIMEOUT_S


def _decompose_further_enabled() -> bool:
    """Gate the decompose-further (defect-localization) loop. Default ON."""
    return os.getenv("VERIFY_DECOMPOSE_FURTHER", "1").strip().lower() not in (
        "0", "false", "no", "off", "")


def _max_repair_attempts() -> int:
    """Hard upper bound on decompose-further narrowing passes (guarantees the
    repeat-until-done loop terminates even before the no-progress guard fires)."""
    try:
        return max(1, int(os.getenv("VERIFY_MAX_REPAIR_ATTEMPTS",
                                    _DEFAULT_MAX_REPAIR_ATTEMPTS)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_REPAIR_ATTEMPTS

# Writers/movers of a field, for honest seam-linking of a defect. Falls back to
# the program node (unresolved) when the graph has no writer — never invents lineage.
_WRITERS_OF_FIELD = """
MATCH (t:CodeEntity {repo:$repo})
WHERE t.qualified_name = $qname OR t.simple_name = $field
MATCH (src:CodeEntity {repo:$repo})-[e:WRITES|MOVES_TO]->(t)
RETURN src.qualified_name AS qualified_name, type(e) AS edge,
       src.file_path AS file_path
LIMIT 5
"""


class _GraphOps:
    """Minimal read-only facade satisfying seam_link.resolve_source_seam."""
    def __init__(self, neo4j, repo: str) -> None:
        self._neo4j = neo4j
        self._repo = repo

    def writers_of_data_item(self, qname: str) -> list[dict]:
        field = qname.split(".")[-1]
        rows = self._neo4j.run(_WRITERS_OF_FIELD, repo=self._repo,
                               qname=qname, field=field)
        return [{"qualified_name": r["qualified_name"], "edge": r.get("edge", ""),
                 "file_path": r.get("file_path") or "", "line": None} for r in rows]


class VerifyRequest(BaseModel):
    program: str
    record: str                       # record/copybook name, e.g. ACCOUNT-RECORD
    record_key: str                   # key field, e.g. ACCT-ID
    golden_records: list[dict] = Field(default_factory=list)   # the COBOL oracle
    candidate_records: list[dict] = Field(default_factory=list)  # generated Java output
    slice_name: str = "default"
    tolerance_yaml: str | None = None
    dialect: str = "unspecified"
    online_uses_recorded_fixtures: bool = False


def evaluate_story_behavior(session: Session, workspace_id: str, *, stories: list[dict],
                            generated_test_refs: list[str], equivalence_verdict: str) -> Gate:
    """Aggregate per-story behavior gates into one verify-stage story_behavior gate.
    A normalized equivalence verdict of 'pass' maps to story_behavior_gate's 'passed'."""
    # story_behavior_gate expects 'passed' (not 'pass'); normalize here.
    verdict = "passed" if equivalence_verdict == "pass" else equivalence_verdict
    failures: list[dict] = []
    for story in stories:
        ac_ids = [c.get("id") for c in story.get("acceptance_criteria", []) if c.get("id")]
        res = story_behavior_gate(story_id=story.get("id", "?"),
                                  acceptance_criteria_ids=ac_ids,
                                  generated_test_refs=generated_test_refs,
                                  equivalence_verdict=verdict)
        if not res["passed"]:
            failures.append(res)
    passed = not failures
    return upsert_gate(session, workspace_id, "verify", "story_behavior",
                       passed=passed, result={"failures": failures},
                       threshold={"all_stories_verified": True})


def _workspace(session: Session, wid: str) -> Workspace:
    ws = session.get(Workspace, wid)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"workspace {wid} not found")
    return ws


def _set_status(session: Session, wid: str, stage_key: str, status: str) -> None:
    for st in session.execute(
        select(JourneyStage).where(JourneyStage.workspace_id == wid,
                                   JourneyStage.stage_key == stage_key)
    ).scalars().all():
        st.status = status


def _serialize_defect(d) -> dict:
    return {
        "source_seam": d.source_seam, "seam_edge_kind": d.seam_edge_kind,
        "source_file": d.source_file, "source_line": d.source_line,
        "field": d.field, "record_key": d.record_key, "reason": d.reason,
        "severity": d.severity, "dialect_note": d.dialect_note,
    }


def _load_stories(neo4j, repo_slug: str) -> list[dict]:
    """The latest backlog's stories for this repo, or [] when there is no backlog."""
    try:
        node = BacklogStorage(neo4j).get_latest(repo_slug)
    except _NEO4J_ERRORS:
        raise
    except Exception:  # noqa: BLE001 — a missing/garbled backlog is just "no fan-out"
        logger.warning("verify: backlog load failed; falling back to single-slice", exc_info=True)
        return []
    if not node:
        return []
    try:
        return json.loads(node.get("stories_json") or "[]") or []
    except (TypeError, ValueError):
        return []


async def _run_one_story(lab: EquivalenceLab, *, workspace_id: str, slice_name: str,
                         program: str, candidate_records: list[dict], record_key: str,
                         online_uses_recorded_fixtures: bool,
                         sem: asyncio.Semaphore, timeout_s: float) -> dict[str, Any]:
    """Run ONE story's equivalence under a SOFT per-story wall. On overrun (or any
    error) return a PARTIAL sub-verdict (ok=False) — never a hard kill / raise — so
    the workspace verdict still synthesizes (loop-until-done). On success the verdict
    + defects are the real deterministic equivalence result."""
    async with sem:
        try:
            coro = lab.run_equivalence_async(
                workspace_id=workspace_id, slice_name=slice_name, program=program,
                candidate_records=candidate_records, record_key=record_key,
                online_uses_recorded_fixtures=online_uses_recorded_fixtures)
            result = await asyncio.wait_for(coro, timeout=timeout_s) if timeout_s > 0 else await coro
        except asyncio.TimeoutError:
            return {"slice_name": slice_name, "ok": False, "reason": "timeout",
                    "verdict": "fail", "defect_count": 0, "defects": [], "partial": True}
        except Exception as exc:  # noqa: BLE001 — partial sub-verdict, never crash the fan-out
            logger.warning("verify: per-story equivalence failed for %s; partial sub-verdict",
                           slice_name, exc_info=True)
            return {"slice_name": slice_name, "ok": False, "reason": f"error: {exc}",
                    "verdict": "fail", "defect_count": 0, "defects": [], "partial": True}
    ok = result.report.verdict == "pass"
    return {
        "slice_name": slice_name, "ok": ok,
        "reason": "equivalence passed" if ok else "equivalence failed",
        "verdict": result.report.verdict,
        "records_compared": result.report.records_compared,
        "defect_count": result.report.defect_count,
        "open_questions": result.report.open_questions,
        "defects": [_serialize_defect(d) for d in result.defects],
        "partial": False,
    }


def _fan_out_per_story(lab: EquivalenceLab, *, workspace_id: str, req: VerifyRequest,
                       stories: list[dict]) -> list[dict[str, Any]]:
    """Register each story's golden then run all stories concurrently (bounded by
    VERIFY_MAX_CONCURRENCY) under a soft per-story timeout. Returns one sub-verdict
    per story, in story order. Golden registration is done up-front (synchronously)
    so the worker threads only read immutable lab state."""
    timeout_s = _equivalence_timeout_s()
    sem = asyncio.Semaphore(_max_concurrency())
    slice_names: list[str] = []
    for story in stories:
        sid = str(story.get("id") or f"story-{len(slice_names)}")
        slice_names.append(sid)
        lab.register_golden(workspace_id=workspace_id, slice_name=sid,
                            record=req.record, records=req.golden_records)

    async def _go() -> list[dict[str, Any]]:
        tasks = [
            _run_one_story(
                lab, workspace_id=workspace_id, slice_name=sid, program=req.program,
                candidate_records=req.candidate_records, record_key=req.record_key,
                online_uses_recorded_fixtures=req.online_uses_recorded_fixtures,
                sem=sem, timeout_s=timeout_s)
            for sid in slice_names
        ]
        return list(await asyncio.gather(*tasks))

    subs = asyncio.run(_go())
    for story, sub in zip(stories, subs):
        sub["story_id"] = str(story.get("id") or sub["slice_name"])
    return subs


def _subslice_verdict(lab: EquivalenceLab, *, workspace_id: str, slice_name: str,
                      subslice: str, program: str, golden: list[dict],
                      candidate: list[dict], record: str, record_key: str,
                      online_uses_recorded_fixtures: bool,
                      timeout_s: float) -> dict[str, Any]:
    """Run equivalence on ONE narrower sub-slice (program/COBOL-context) under the
    SAME soft-timeout philosophy as the per-story fan-out: an overrun (or any
    error) yields a PARTIAL sub-verdict (ok=False), never a hard kill. Registers a
    sub-slice-scoped golden (only this sub-slice's golden records) so the re-run is
    a TRUE narrowing of the failing story onto this program/context."""
    sub_name = f"{slice_name}::{subslice}"
    lab.register_golden(workspace_id=workspace_id, slice_name=sub_name,
                        record=record, records=golden)

    async def _go():
        coro = lab.run_equivalence_async(
            workspace_id=workspace_id, slice_name=sub_name, program=program,
            candidate_records=candidate, record_key=record_key,
            online_uses_recorded_fixtures=online_uses_recorded_fixtures)
        return await (asyncio.wait_for(coro, timeout=timeout_s)
                      if timeout_s > 0 else coro)

    try:
        result = asyncio.run(_go())
    except asyncio.TimeoutError:
        return {"subslice": subslice, "ok": False, "reason": "timeout",
                "verdict": "fail", "defect_count": 0, "defects": [], "partial": True}
    except Exception as exc:  # noqa: BLE001 — partial sub-verdict, never crash decompose
        logger.warning("verify: sub-slice equivalence failed for %s; partial sub-verdict",
                       sub_name, exc_info=True)
        return {"subslice": subslice, "ok": False, "reason": f"error: {exc}",
                "verdict": "fail", "defect_count": 0, "defects": [], "partial": True}
    ok = result.report.verdict == "pass"
    return {
        "subslice": subslice, "ok": ok,
        "reason": "equivalence passed" if ok else "equivalence failed",
        "verdict": result.report.verdict,
        "records_compared": result.report.records_compared,
        "defect_count": result.report.defect_count,
        "open_questions": result.report.open_questions,
        "defects": [_serialize_defect(d) for d in result.defects],
        "partial": False,
    }


def _decompose_story(lab: EquivalenceLab, *, workspace_id: str, req: VerifyRequest,
                     slice_name: str) -> list[dict[str, Any]] | None:
    """DECOMPOSE-FURTHER repeat-until-done: split a FAILING story's records per
    program/COBOL-context and re-run equivalence on each narrower sub-slice to
    LOCALIZE which sub-slice actually fails. Returns the leaf sub-slice verdicts,
    or None when no meaningful split exists (a single context → nothing to localize).

    Termination is guaranteed two ways: (1) a hard attempt bound
    (VERIFY_MAX_REPAIR_ATTEMPTS), and (2) a no-progress guard — a failing
    sub-slice that does not split into >1 child is atomic and is not re-queued."""
    cand_groups = split_by_subslice(req.candidate_records)
    if len(cand_groups) <= 1:
        return None  # one context only — no localization possible
    golden_groups = split_by_subslice(req.golden_records)
    timeout_s = _equivalence_timeout_s()
    max_attempts = _max_repair_attempts()

    # Work queue of (subslice_key, candidate_records, golden_records) to localize.
    pending = [(k, v, golden_groups.get(k, [])) for k, v in cand_groups.items()]
    leaves: list[dict[str, Any]] = []
    attempt = 0
    while pending and attempt < max_attempts:
        attempt += 1
        next_pending: list[tuple[str, list[dict], list[dict]]] = []
        for key, cand, golden in pending:
            sub = _subslice_verdict(
                lab, workspace_id=workspace_id, slice_name=slice_name, subslice=key,
                program=req.program, golden=golden, candidate=cand,
                record=req.record, record_key=req.record_key,
                online_uses_recorded_fixtures=req.online_uses_recorded_fixtures,
                timeout_s=timeout_s)
            if sub["ok"]:
                leaves.append(sub)
                continue
            # Try to narrow this failing sub-slice FURTHER (loop-until-done). A
            # split that does NOT increase the group count is no-progress → atomic.
            child_groups = split_by_subslice(cand)
            if len(child_groups) > 1:
                child_golden = split_by_subslice(golden)
                next_pending.extend(
                    (ck, cv, child_golden.get(ck, []))
                    for ck, cv in child_groups.items())
            else:
                leaves.append(sub)  # atomic failing leaf — localized here
        pending = next_pending
    # Attempt bound hit with work still pending: record those as localized leaves
    # (we stop narrowing — never an infinite loop).
    for key, cand, golden in pending:
        sub = _subslice_verdict(
            lab, workspace_id=workspace_id, slice_name=slice_name, subslice=key,
            program=req.program, golden=golden, candidate=cand,
            record=req.record, record_key=req.record_key,
            online_uses_recorded_fixtures=req.online_uses_recorded_fixtures,
            timeout_s=timeout_s)
        leaves.append(sub)
    return leaves


def _make_lab(neo4j, *, repo_slug: str, req: VerifyRequest) -> EquivalenceLab:
    ruleset = load_ruleset(
        req.tolerance_yaml
        or f"record: {req.record}\ndefault:\n  matcher: exact\n")
    ops = _GraphOps(neo4j, repo_slug)

    def resolve_seam(program: str, field: str):
        return resolve_source_seam(ops, program=program, field=field)

    return EquivalenceLab(golden_store=InMemoryGoldenStore(), ruleset=ruleset,
                          resolve_seam=resolve_seam, dialect=req.dialect)


def run_verify(*, session: Session, neo4j, workspace: Workspace,
               req: VerifyRequest) -> dict[str, Any]:
    if not req.golden_records:
        raise HTTPException(
            status_code=409,
            detail="no golden master supplied — capture the COBOL oracle output "
                   "for this slice first, then re-run Verify with it.")

    lab = _make_lab(neo4j, repo_slug=workspace.repo_slug, req=req)
    stories = _load_stories(neo4j, workspace.repo_slug)

    if stories:
        return _run_verify_fanout(session=session, neo4j=neo4j, workspace=workspace,
                                  req=req, lab=lab, stories=stories)
    return _run_verify_single(session=session, neo4j=neo4j, workspace=workspace,
                              req=req, lab=lab)


def _run_verify_single(*, session: Session, neo4j, workspace: Workspace,
                       req: VerifyRequest, lab: EquivalenceLab) -> dict[str, Any]:
    """Today's behavior: no backlog -> one slice, one verify_report."""
    lab.register_golden(workspace_id=workspace.id, slice_name=req.slice_name,
                        record=req.record, records=req.golden_records)
    result = lab.run_equivalence(
        workspace_id=workspace.id, slice_name=req.slice_name, program=req.program,
        candidate_records=req.candidate_records, record_key=req.record_key,
        online_uses_recorded_fixtures=req.online_uses_recorded_fixtures)

    _set_status(session, workspace.id, "verify",
                "passed" if result.report.verdict == "pass" else "failed")

    payload = {
        "repo_slug": workspace.repo_slug,
        "verdict": result.report.verdict,
        "records_compared": result.report.records_compared,
        "defect_count": result.report.defect_count,
        "open_questions": result.report.open_questions,
        "defects": [_serialize_defect(d) for d in result.defects],
    }

    # Durable, versioned record of this verify run (max(prev)+1) so the verdict
    # survives a refresh and GET /verify/status can replay it. Mirrors build's
    # `_record_generated_test_refs` Artifact-versioning pattern.
    art = record_verify_report(session, workspace_id=workspace.id,
                               evidence_map=dict(payload))

    session.flush()
    return {**payload, "version": art.version}


def _run_verify_fanout(*, session: Session, neo4j, workspace: Workspace,
                       req: VerifyRequest, lab: EquivalenceLab,
                       stories: list[dict]) -> dict[str, Any]:
    """Fan-Out-and-Synthesize: one equivalence check PER story (each story's ACs cite
    different COBOL seams), bounded concurrency + soft per-story timeout. The workspace
    passes iff EVERY story passes equivalence AND story_behavior."""
    subs = _fan_out_per_story(lab, workspace_id=workspace.id, req=req, stories=stories)

    # DECOMPOSE-FURTHER (defect localization): for each FAILING story, split its
    # records per program/COBOL-context and re-run to pin WHICH sub-slice fails.
    # A parent story PASSES iff ALL its sub-verdicts pass (the whole-story verdict
    # already failed here; decompose only localizes — it never flips fail->pass).
    failing_subslices: list[str] = []
    if _decompose_further_enabled():
        for sub in subs:
            if sub["ok"]:
                continue
            leaves = _decompose_story(lab, workspace_id=workspace.id, req=req,
                                      slice_name=sub["slice_name"])
            if not leaves:
                continue
            sub["subslices"] = leaves
            failing_subslices.extend(
                s["subslice"] for s in leaves if not s["ok"])

    # Persist one equivalence_check Artifact per story (incl. partial/timeout subs
    # and any localized sub-slice results from decompose-further).
    for sub in subs:
        record_equivalence_check(
            session, workspace_id=workspace.id, story_id=sub["story_id"],
            evidence_map={
                "story_id": sub["story_id"],
                "slice_name": sub["slice_name"],
                "verdict": sub["verdict"],
                "ok": sub["ok"],
                "reason": sub.get("reason", ""),
                "defect_count": sub.get("defect_count", 0),
                "defects_json": json.dumps(sub.get("defects", [])),
                "partial": sub.get("partial", False),
                "subslices_json": json.dumps(sub.get("subslices", [])),
                "failing_subslices": [s["subslice"] for s in sub.get("subslices", [])
                                      if not s["ok"]],
            })

    equivalence_passed = bool(subs) and all(s["ok"] for s in subs)
    total_defects = sum(s.get("defect_count", 0) for s in subs)
    total_compared = sum(s.get("records_compared", 0) for s in subs)
    open_questions = [q for s in subs for q in s.get("open_questions", [])]

    _set_status(session, workspace.id, "verify",
                "passed" if equivalence_passed else "failed")

    # Synthesize the equivalence gate (human-resolved gates stay immutable — see
    # upsert_gate semantics). The synthesized verdict drives the story_behavior gate too.
    synth_verdict = "pass" if equivalence_passed else "fail"
    upsert_gate(session, workspace.id, "verify", "equivalence",
                passed=equivalence_passed,
                result={"per_story_verdicts": subs, "defect_count": total_defects},
                threshold={"all_stories_pass_equivalence": True})

    # Story-behavior gate (additive — never raises; never breaks equivalence verdict).
    try:
        refs_art = session.execute(
            select(Artifact).where(Artifact.workspace_id == workspace.id,
                                   Artifact.kind == "generated_test_refs")
            .order_by(Artifact.version.desc())
        ).scalars().first()
        test_refs = (refs_art.evidence_map or {}).get("acceptance_criteria", []) if refs_art else []
        evaluate_story_behavior(session, workspace.id, stories=stories,
                                generated_test_refs=test_refs,
                                equivalence_verdict=synth_verdict)
    except Exception:  # noqa: BLE001 — story gate is additive; never break equivalence verify
        logger.warning("verify: story-behavior gate evaluation failed; equivalence verdict stands",
                       exc_info=True)

    payload = {
        "repo_slug": workspace.repo_slug,
        "verdict": synth_verdict,
        "records_compared": total_compared,
        "defect_count": total_defects,
        "open_questions": open_questions,
        "defects": [d for s in subs for d in s.get("defects", [])],
        "per_story_verdicts": subs,
        # Localized: the narrower program/COBOL-context sub-slices that actually
        # failed (deduped, order-preserving). Empty when nothing decomposed.
        "failing_subslices": list(dict.fromkeys(failing_subslices)),
    }
    art = record_verify_report(session, workspace_id=workspace.id,
                               evidence_map=dict(payload))
    session.flush()
    return {**payload, "version": art.version}


@router.post("/workspaces/{wid}/verify")
def verify_workspace(wid: str, req: VerifyRequest,
                     session: Session = Depends(get_session),
                     neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    try:
        return run_verify(session=session, neo4j=neo4j, workspace=ws, req=req)
    except HTTPException:
        raise
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")


def _verify_stage_status(session: Session, wid: str) -> str | None:
    return session.execute(
        select(JourneyStage.status).where(JourneyStage.workspace_id == wid,
                                          JourneyStage.stage_key == "verify")
    ).scalars().first()


@router.get("/workspaces/{wid}/verify/status")
def verify_status(wid: str, session: Session = Depends(get_session)) -> dict:
    """Replay the latest persisted `verify_report` Artifact so the verdict survives
    a refresh (durable re-trigger). Mirrors the other `*_status` GETs: `idle` when
    no run has been persisted, else `done` + the latest report (+ the verify stage
    status as the gate view)."""
    ws = _workspace(session, wid)
    art = latest_verify_report(session, ws.id)
    if art is None:
        return {"status": "idle", "result": None, "error": None,
                "started_at": None, "finished_at": None}
    ev = art.evidence_map or {}
    result = {
        "version": art.version,
        "repo_slug": ev.get("repo_slug", ws.repo_slug),
        "verdict": ev.get("verdict"),
        "records_compared": ev.get("records_compared"),
        "defect_count": ev.get("defect_count"),
        "open_questions": ev.get("open_questions"),
        "defects": ev.get("defects", []),
        # Fanned-out per-story sub-verdicts + decompose-further localization are
        # persisted in evidence_map; surface them so the cockpit can lazy-load the
        # per-story verdicts / failing sub-slices / Repair actions on refresh.
        "per_story_verdicts": ev.get("per_story_verdicts", []),
        "failing_subslices": ev.get("failing_subslices", []),
        "stage_status": _verify_stage_status(session, ws.id),
    }
    return {"status": "done", "result": result, "error": None,
            "started_at": None, "finished_at": None}
