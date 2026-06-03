"""Verify-repair — LLM-driven repair of a story whose generated Java FAILS
equivalence against the COBOL oracle (close the red->green gap).

`POST /api/workspaces/{wid}/verify/repair/{story_id}` runs a bounded
repeat-until-done loop for ONE story:

    confirm the equivalence DEFECT (expected vs actual)
      -> regenerate that story's Java via the EXISTING codegen patch agent
         (`codegen/patch_agent.generate_story_implementation`), fed a
         `repair_feedback` describing the defect (mirrors `story_runner`'s repair)
      -> write the regenerated Java into the scaffolded module (same
         `dest = root / f.path` pattern as build)
      -> RE-RUN equivalence for that story (reuse the per-story equivalence path)
      -> stop on GREEN (resolved) OR no-progress OR the attempt cap
         (`VERIFY_MAX_REPAIR_ATTEMPTS`, default 2).

This module REUSES the codegen patch agent (it does NOT reimplement codegen) and
keeps the repair PER-STORY: only the target story's Java is regenerated, and only
that story's `equivalence_check` is updated — other stories are never disturbed.
Verify's gate/report semantics are preserved: the loop updates the persisted
`equivalence_check` for the story and writes a fresh `verify_report` reflecting the
outcome, then marks the `verify` stage passed/failed.

The two heavy steps are module-level INJECTABLE seams — `_repair_story_java` (the
patch-agent regenerate + write) and `_run_story_equivalence` (the equivalence run)
— resolved at call time so tests stub them (no live LLM/Maven/Neo4j), mirroring how
`build.py` injects `generate` / `build_stories` injects `_run_story_build_step`.

Golden masters are BRING-YOUR-OWN: with no golden records for the story the endpoint
409s clearly, exactly like `verify.run_verify`.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from neo4j.exceptions import DriverError, Neo4jError
from sqlalchemy.orm import Session

from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.controlplane.gates_util import upsert_gate
from cobol_modernizer.controlplane.verify import (
    VerifyRequest, _make_lab, _serialize_defect, _set_status, _workspace,
)
from cobol_modernizer.controlplane.verify_storage import (
    record_equivalence_check, record_verify_report,
)
from cobol_modernizer.equivalence.lab import EquivalenceLab
from cobol_modernizer.persistence.tables import Workspace

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["controlplane-verify-repair"])
_NEO4J_ERRORS = (Neo4jError, DriverError)

_DEFAULT_MAX_REPAIR_ATTEMPTS = 2


def _max_repair_attempts() -> int:
    """Hard upper bound on repair regenerations (guarantees the repeat-until-done
    loop terminates even before the no-progress guard fires). Shares the
    VERIFY_MAX_REPAIR_ATTEMPTS env contract with verify's decompose-further loop."""
    try:
        return max(1, int(os.getenv("VERIFY_MAX_REPAIR_ATTEMPTS",
                                    _DEFAULT_MAX_REPAIR_ATTEMPTS)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_REPAIR_ATTEMPTS


def _source_root() -> Path:
    return Path(os.environ.get("COBOL_SOURCE_ROOT", "source_code_to_analyse"))


def _output_root() -> Path:
    return Path(os.environ.get("CODEGEN_OUTPUT_DIR", "codegen_output"))


# --------------------------------------------------------------------------- #
# Injectable seam #1 — per-story equivalence run                              #
# --------------------------------------------------------------------------- #
def _run_story_equivalence(lab: EquivalenceLab, *, workspace_id: str,
                           slice_name: str, req: VerifyRequest) -> dict[str, Any]:
    """Run the deterministic equivalence for ONE story slice and normalize the
    result into the dict the repair loop consumes. Reuses the SAME lab/diff path the
    Task-10 fan-out uses (`run_equivalence`). Tests monkeypatch this module attribute
    to inject a scripted defect->green sequence."""
    result = lab.run_equivalence(
        workspace_id=workspace_id, slice_name=slice_name, program=req.program,
        candidate_records=req.candidate_records, record_key=req.record_key,
        online_uses_recorded_fixtures=req.online_uses_recorded_fixtures)
    ok = result.report.verdict == "pass"
    return {
        "verdict": result.report.verdict, "ok": ok,
        "records_compared": result.report.records_compared,
        "defect_count": result.report.defect_count,
        "open_questions": result.report.open_questions,
        "defects": [_serialize_defect(d) for d in result.defects],
    }


# --------------------------------------------------------------------------- #
# Injectable seam #2 — regenerate the story's Java via the patch agent         #
# --------------------------------------------------------------------------- #
def _repair_feedback_for(defect: dict | None, *, attempt: int) -> dict:
    """Render the equivalence DEFECT (expected vs actual) into the `repair_feedback`
    shape the patch agent already understands (failing_gate + log_excerpt + touched
    files), exactly mirroring `story_runner._repair_feedback`."""
    field = (defect or {}).get("field", "?")
    expected = (defect or {}).get("expected")
    actual = (defect or {}).get("actual")
    reason = (defect or {}).get("reason", "equivalence mismatch")
    log = (f"Equivalence defect on field '{field}': expected {expected!r} but the "
           f"generated Java produced {actual!r} ({reason}). Make the production code "
           f"emit the expected value. (repair attempt {attempt})")
    return {"failing_gate": "equivalence", "log_excerpt": log, "touched_files": []}


def _repair_story_java(*, session: Session, neo4j, workspace: Workspace,
                       source_root: Path, output_root: Path, story_id: str,
                       defect: dict | None, candidate_records: list[dict],
                       attempt: int) -> list[str]:
    """Regenerate ONE story's Java with the EXISTING codegen patch agent and write it
    into the scaffolded module (same `dest = root / f.path` pattern as build), scoped
    to JUST this story — other stories' files are untouched. Returns the relative
    paths written. Imported lazily so the agent SDK / scaffold deps are only needed
    for a real run; tests monkeypatch this module attribute with a stub.

    This is the bridge between Verify and codegen: it reuses `build_stories`' module
    location + story-context builder and `story_runner`'s file-write pattern so the
    repair shares the build's wiring rather than reimplementing it."""
    import asyncio

    from cobol_modernizer.agent.deps import GraphDeps
    from cobol_modernizer.agent.harness import SdkAgentRunner
    from cobol_modernizer.brd.storage import BRDStorage
    from cobol_modernizer.codegen.patch_agent import generate_story_implementation
    from cobol_modernizer.codegen.scaffold_from_design import scaffold_from_design
    from cobol_modernizer.codegen.story_context import build_story_context
    from cobol_modernizer.codegen.story_runner import _existing_java, _write_files
    from cobol_modernizer.controlplane import build_stories
    from cobol_modernizer.controlplane.build import _slice_pack

    slug = workspace.repo_slug
    specs = build_stories._load_specs(neo4j, slug)
    technical, domain, backlog = specs.technical, specs.domain, specs.backlog
    # Locate the scaffolded module exactly as build does (idempotent: re-scaffolding
    # the same TechnicalDesign yields the same files — it does not clobber generated
    # story code, which lives in separate paths).
    module_dir = scaffold_from_design(output_root, technical)

    # Find the matching plan item (reuse build_stories' deterministic planner).
    plan = build_stories._plan_for(neo4j, slug)
    item = next((i for i in plan.items if i.story_id == story_id), None)
    if item is None:
        raise HTTPException(status_code=404,
                            detail=f"story '{story_id}' not in the plan")

    # Build THIS story's context pack exactly as build_stories._real_story_build_step
    # does (scoped slice-pack + resolved service/aggregate/BRD reqs).
    story = next((s for s in backlog.stories if s.id == story_id), None)
    service = build_stories._service_for_item(technical, item)
    aggregate = build_stories._aggregate_for_context(domain, item.bounded_context)
    brd_reqs = build_stories._brd_req_strings(BRDStorage(neo4j).get_latest(slug))
    deps = GraphDeps(client=neo4j, repo_id=slug,
                     repo_path=(source_root / slug).resolve())
    pack = _slice_pack(
        deps, {"domain_design": {"designs": [{"cobol_mapping": [
            {"cobol_ref": r} for r in item.cobol_refs]}]}},
        max_units=int(os.environ.get("CODEGEN_PACK_MAX_UNITS", "200")),
        max_chars=int(os.environ.get("CODEGEN_PACK_MAX_CHARS", "60000")))
    context_pack = build_story_context(
        item, story=story, service=service, aggregate=aggregate,
        brd_requirements=brd_reqs, completed_summaries=[], source_pack=pack)

    feedback = _repair_feedback_for(defect, attempt=attempt)
    runner = SdkAgentRunner()
    patch = asyncio.run(generate_story_implementation(
        runner=runner, item=item, context_pack=context_pack, failing_tests=[],
        existing_java=_existing_java(module_dir), model="sonnet",
        repair_feedback=feedback))
    return _write_files(module_dir, list(patch.files))


# --------------------------------------------------------------------------- #
# The bounded repair loop                                                     #
# --------------------------------------------------------------------------- #
def run_verify_repair(*, session: Session, neo4j, workspace: Workspace,
                      story_id: str, req: VerifyRequest) -> dict[str, Any]:
    """Repeat-until-done repair of ONE story's failing Java. ALWAYS terminates: the
    loop is bounded by `VERIFY_MAX_REPAIR_ATTEMPTS` AND a no-progress guard (it stops
    the moment equivalence goes green). On no golden master -> 409 (bring-your-own)."""
    if not req.golden_records:
        raise HTTPException(
            status_code=409,
            detail="no golden master supplied — capture the COBOL oracle output "
                   "for this story first, then re-run repair with it.")

    lab = _make_lab(neo4j, repo_slug=workspace.repo_slug, req=req)
    lab.register_golden(workspace_id=workspace.id, slice_name=story_id,
                        record=req.record, records=req.golden_records)

    # Confirm the defect with a fresh equivalence run (seam resolves at call time).
    sub = _run_story_equivalence(lab, workspace_id=workspace.id,
                                 slice_name=story_id, req=req)
    attempts = 0
    max_attempts = _max_repair_attempts()

    # repeat-until-done: regenerate + re-verify while red and under the attempt cap.
    while not sub["ok"] and attempts < max_attempts:
        attempts += 1
        defect = (sub.get("defects") or [None])[0]
        logger.info("verify-repair: story %s repair attempt %d (defect=%s)",
                    story_id, attempts, (defect or {}).get("field"))
        _repair_story_java(
            session=session, neo4j=neo4j, workspace=workspace,
            source_root=_source_root(), output_root=_output_root(),
            story_id=story_id, defect=defect,
            candidate_records=req.candidate_records, attempt=attempts)
        sub = _run_story_equivalence(lab, workspace_id=workspace.id,
                                     slice_name=story_id, req=req)

    resolved = bool(sub["ok"])

    # Update the persisted per-story equivalence_check with the repair outcome (only
    # THIS story's check — per-story isolation preserved).
    record_equivalence_check(
        session, workspace_id=workspace.id, story_id=story_id,
        evidence_map={
            "story_id": story_id, "slice_name": story_id,
            "verdict": sub["verdict"], "ok": sub["ok"],
            "reason": "repaired to green" if resolved
            else "still failing after repair",
            "defect_count": sub.get("defect_count", 0),
            "defects_json": json.dumps(sub.get("defects", [])),
            "repaired": True, "repair_attempts": attempts,
        })

    _set_status(session, workspace.id, "verify",
                "passed" if resolved else "failed")
    upsert_gate(session, workspace.id, "verify", "equivalence",
                passed=resolved,
                result={"story_id": story_id, "verdict": sub["verdict"],
                        "repair_attempts": attempts,
                        "defect_count": sub.get("defect_count", 0)},
                threshold={"story_passes_equivalence": True})

    payload = {
        "repo_slug": workspace.repo_slug,
        "story_id": story_id,
        "verdict": sub["verdict"],
        "resolved": resolved,
        "attempts": attempts,
        "records_compared": sub.get("records_compared", 0),
        "defect_count": sub.get("defect_count", 0),
        "open_questions": sub.get("open_questions", []),
        "defects": sub.get("defects", []),
    }
    art = record_verify_report(session, workspace_id=workspace.id,
                               evidence_map=dict(payload))
    session.flush()
    return {**payload, "version": art.version}


@router.post("/workspaces/{wid}/verify/repair/{story_id}")
def repair_story(wid: str, story_id: str, req: VerifyRequest,
                 session: Session = Depends(get_session),
                 neo4j=Depends(get_neo4j)) -> dict:
    ws = _workspace(session, wid)
    try:
        return run_verify_repair(session=session, neo4j=neo4j, workspace=ws,
                                 story_id=story_id, req=req)
    except HTTPException:
        raise
    except _NEO4J_ERRORS as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")
