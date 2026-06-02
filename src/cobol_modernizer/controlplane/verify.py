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

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from neo4j.exceptions import DriverError, Neo4jError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from cobol_modernizer.backlog.storage import BacklogStorage
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.controlplane.gates_util import upsert_gate
from cobol_modernizer.equivalence.golden import InMemoryGoldenStore
from cobol_modernizer.equivalence.lab import EquivalenceLab
from cobol_modernizer.equivalence.seam_link import resolve_source_seam
from cobol_modernizer.equivalence.tolerance import load_ruleset
from cobol_modernizer.persistence.tables import Artifact, Gate, JourneyStage, Workspace
from cobol_modernizer.slice.gates import story_behavior_gate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["controlplane-verify"])
_NEO4J_ERRORS = (Neo4jError, DriverError)

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


def run_verify(*, session: Session, neo4j, workspace: Workspace,
               req: VerifyRequest) -> dict[str, Any]:
    if not req.golden_records:
        raise HTTPException(
            status_code=409,
            detail="no golden master supplied — capture the COBOL oracle output "
                   "for this slice first, then re-run Verify with it.")
    ruleset = load_ruleset(
        req.tolerance_yaml
        or f"record: {req.record}\ndefault:\n  matcher: exact\n")

    ops = _GraphOps(neo4j, workspace.repo_slug)

    def resolve_seam(program: str, field: str):
        return resolve_source_seam(ops, program=program, field=field)

    lab = EquivalenceLab(golden_store=InMemoryGoldenStore(), ruleset=ruleset,
                         resolve_seam=resolve_seam, dialect=req.dialect)
    lab.register_golden(workspace_id=workspace.id, slice_name=req.slice_name,
                        record=req.record, records=req.golden_records)
    result = lab.run_equivalence(
        workspace_id=workspace.id, slice_name=req.slice_name, program=req.program,
        candidate_records=req.candidate_records, record_key=req.record_key,
        online_uses_recorded_fixtures=req.online_uses_recorded_fixtures)

    _set_status(session, workspace.id, "verify",
                "passed" if result.report.verdict == "pass" else "failed")

    # Story-behavior gate (additive — never raises; never breaks equivalence verdict).
    try:
        backlog_node = BacklogStorage(neo4j).get_latest(workspace.repo_slug)
        stories = json.loads(backlog_node.get("stories_json") or "[]") if backlog_node else []
        if stories:
            refs_art = session.execute(
                select(Artifact).where(Artifact.workspace_id == workspace.id,
                                       Artifact.kind == "generated_test_refs")
                .order_by(Artifact.version.desc())
            ).scalars().first()
            test_refs = (refs_art.evidence_map or {}).get("acceptance_criteria", []) if refs_art else []
            evaluate_story_behavior(session, workspace.id, stories=stories,
                                    generated_test_refs=test_refs,
                                    equivalence_verdict=result.report.verdict)
    except Exception:  # noqa: BLE001 — story gate is additive; never break equivalence verify
        logger.warning("verify: story-behavior gate evaluation failed; equivalence verdict stands",
                       exc_info=True)

    session.flush()
    return {
        "repo_slug": workspace.repo_slug,
        "verdict": result.report.verdict,
        "records_compared": result.report.records_compared,
        "defect_count": result.report.defect_count,
        "open_questions": result.report.open_questions,
        "defects": [_serialize_defect(d) for d in result.defects],
    }


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
