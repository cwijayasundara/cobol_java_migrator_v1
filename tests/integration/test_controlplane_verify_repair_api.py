"""Verify-repair endpoint: LLM-driven repair of a story whose generated Java FAILS
equivalence against the COBOL oracle. The repair loop regenerates the Java (reusing
the codegen patch agent) and RE-RUNS equivalence, repeat-until-done, bounded by
VERIFY_MAX_REPAIR_ATTEMPTS.

Both heavy seams are INJECTABLE and stubbed here (no live LLM/Maven/Neo4j):
  - `_repair_story_java` (the patch-agent regenerate + write into the scaffold), and
  - `_run_story_equivalence` (the per-story equivalence run) is driven by a scripted
    defect -> green (or stays-red) sequence.

Covers: a defect repaired to green (report updated, story passes); a repair that
EXHAUSTS attempts (equivalence stays red -> story stays failed, loop terminates,
bounded); and the no-golden 409.
"""
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from cobol_modernizer.persistence.tables import Base, Workspace, JourneyStage, Artifact, WorkUnit
from cobol_modernizer.api import app
from cobol_modernizer.controlplane import verify_repair as vr
from cobol_modernizer.controlplane.deps import get_session, get_neo4j


class _FakeNeo4j:
    def run(self, query, **params):
        return []


def _client(neo4j=None):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Workspace(id="ws-1", name="m", repo_slug="carddemo-mini", created_by="x"))
        s.add(JourneyStage(id="stg-v", workspace_id="ws-1", stage_key="verify",
                           ordinal=10, status="failed"))
        s.commit()

    def _ov():
        ss = Session(eng)
        try:
            yield ss
            ss.commit()
        finally:
            ss.close()

    neo = neo4j or _FakeNeo4j()
    app.dependency_overrides[get_session] = _ov
    app.dependency_overrides[get_neo4j] = lambda: neo
    return TestClient(app), eng


def _stage(eng):
    with Session(eng) as s:
        return s.execute(select(JourneyStage.status).where(
            JourneyStage.stage_key == "verify")).scalar_one()


def _verify_reports(eng):
    with Session(eng) as s:
        return s.execute(
            select(Artifact).where(Artifact.workspace_id == "ws-1",
                                   Artifact.kind == "verify_report")
            .order_by(Artifact.version)
        ).scalars().all()


def _equiv_checks(eng):
    with Session(eng) as s:
        return s.execute(
            select(Artifact).where(Artifact.workspace_id == "ws-1",
                                   Artifact.kind == "equivalence_check")
            .order_by(Artifact.version)
        ).scalars().all()


def _work_units(eng):
    with Session(eng) as s:
        return s.execute(
            select(WorkUnit).where(WorkUnit.workspace_id == "ws-1",
                                   WorkUnit.stage == "verify")
            .order_by(WorkUnit.created_at, WorkUnit.id)
        ).scalars().all()


_BODY = {
    "program": "CBPOST1M", "record": "ACCT-RECORD", "record_key": "ID",
    "golden_records": [{"ID": "1", "BAL": "100.00"}],
    "candidate_records": [{"ID": "1", "BAL": "100.06"}],
}


def _scripted_equivalence(verdicts):
    """Return a stub for the `_run_story_equivalence` seam that yields the given
    verdict sequence (a list of 'pass'/'fail'), one per call."""
    seq = list(verdicts)

    def _stub(lab, *, workspace_id, slice_name, req):
        verdict = seq.pop(0) if seq else "fail"
        ok = verdict == "pass"
        return {
            "verdict": verdict, "ok": ok,
            "records_compared": 1,
            "defect_count": 0 if ok else 1,
            "open_questions": [],
            "defects": [] if ok else [{"field": "BAL", "reason": "scale drift",
                                       "expected": "100.00", "actual": "100.06"}],
        }

    return _stub


# --------------------------------------------------------------------------- #
# 409 — no golden records (bring-your-own oracle)
# --------------------------------------------------------------------------- #
def test_repair_409_without_golden():
    c, eng = _client()
    try:
        body = dict(_BODY)
        body["golden_records"] = []
        assert c.post("/api/workspaces/ws-1/verify/repair/S1",
                      json=body).status_code == 409
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Defect -> repair regenerates Java -> re-run equivalence green -> story passes
# --------------------------------------------------------------------------- #
def test_repair_defect_then_green(monkeypatch):
    repaired = {"calls": 0}

    def _fake_repair(*, session, neo4j, workspace, source_root, output_root,
                     story_id, defect, candidate_records, attempt):
        repaired["calls"] += 1
        return ["src/main/java/Posting.java"]

    monkeypatch.setattr(vr, "_repair_story_java", _fake_repair)
    # First equivalence (confirm defect) fails; after one repair it's green.
    monkeypatch.setattr(vr, "_run_story_equivalence",
                        _scripted_equivalence(["fail", "pass"]))

    c, eng = _client()
    try:
        body = c.post("/api/workspaces/ws-1/verify/repair/S1", json=_BODY).json()
        assert body["story_id"] == "S1"
        assert body["verdict"] == "pass"
        assert body["resolved"] is True
        assert body["attempts"] == 1
        assert repaired["calls"] == 1
        # The persisted equivalence_check for the story now reads pass.
        checks = _equiv_checks(eng)
        s1 = [ck for ck in checks if ck.evidence_map.get("story_id") == "S1"][-1]
        assert s1.evidence_map["verdict"] == "pass"
        # A fresh verify_report is persisted reflecting the repair outcome.
        reports = _verify_reports(eng)
        assert reports[-1].evidence_map["verdict"] == "pass"
        units = _work_units(eng)
        assert [(u.unit_type, u.unit_key, u.status) for u in units] == [
            ("verify-repair-equivalence", "S1:confirm", "failed"),
            ("verify-repair-codegen", "S1:attempt-1", "succeeded"),
            ("verify-repair-equivalence", "S1:attempt-1", "succeeded"),
        ]
        assert units[1].payload["changed_files"] == ["src/main/java/Posting.java"]
        assert _stage(eng) == "passed"
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Already green -> nothing to repair (no patch-agent call)
# --------------------------------------------------------------------------- #
def test_repair_noop_when_already_green(monkeypatch):
    repaired = {"calls": 0}

    def _fake_repair(**kwargs):
        repaired["calls"] += 1
        return []

    monkeypatch.setattr(vr, "_repair_story_java", _fake_repair)
    monkeypatch.setattr(vr, "_run_story_equivalence",
                        _scripted_equivalence(["pass"]))

    c, eng = _client()
    try:
        body = c.post("/api/workspaces/ws-1/verify/repair/S1", json=_BODY).json()
        assert body["verdict"] == "pass"
        assert body["resolved"] is True
        assert body["attempts"] == 0
        assert repaired["calls"] == 0  # never touched the patch agent
        units = _work_units(eng)
        assert [(u.unit_type, u.unit_key, u.status) for u in units] == [
            ("verify-repair-equivalence", "S1:confirm", "succeeded"),
        ]
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Repair EXHAUSTS attempts (stays red) -> story stays failed, loop terminates
# --------------------------------------------------------------------------- #
def test_repair_exhausts_attempts_stays_failed(monkeypatch):
    repaired = {"calls": 0}

    def _fake_repair(**kwargs):
        repaired["calls"] += 1
        return ["src/main/java/Posting.java"]

    monkeypatch.setattr(vr, "_repair_story_java", _fake_repair)
    # Equivalence NEVER goes green -> the bounded loop must terminate.
    monkeypatch.setattr(vr, "_run_story_equivalence",
                        _scripted_equivalence(["fail"] * 50))
    monkeypatch.setenv("VERIFY_MAX_REPAIR_ATTEMPTS", "2")

    c, eng = _client()
    try:
        body = c.post("/api/workspaces/ws-1/verify/repair/S1", json=_BODY).json()
        assert body["verdict"] == "fail"
        assert body["resolved"] is False
        # Bounded: exactly the attempt cap of regenerations, no infinite loop.
        assert body["attempts"] == 2
        assert repaired["calls"] == 2
        # The surfaced defect is still present on the failing story.
        assert body["defects"]
        assert body["defects"][0]["field"] == "BAL"
        # Persisted equivalence_check still red; stage stays failed.
        checks = _equiv_checks(eng)
        s1 = [ck for ck in checks if ck.evidence_map.get("story_id") == "S1"][-1]
        assert s1.evidence_map["verdict"] == "fail"
        units = _work_units(eng)
        assert [(u.unit_type, u.unit_key, u.status) for u in units] == [
            ("verify-repair-equivalence", "S1:confirm", "failed"),
            ("verify-repair-codegen", "S1:attempt-1", "succeeded"),
            ("verify-repair-equivalence", "S1:attempt-1", "failed"),
            ("verify-repair-codegen", "S1:attempt-2", "succeeded"),
            ("verify-repair-equivalence", "S1:attempt-2", "failed"),
        ]
        assert _stage(eng) == "failed"
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Per-story isolation: a repair persists ONLY the target story's check.
# --------------------------------------------------------------------------- #
def test_repair_is_per_story(monkeypatch):
    def _fake_repair(**kwargs):
        return ["src/main/java/Posting.java"]

    monkeypatch.setattr(vr, "_repair_story_java", _fake_repair)
    monkeypatch.setattr(vr, "_run_story_equivalence",
                        _scripted_equivalence(["fail", "pass"]))

    c, eng = _client()
    try:
        c.post("/api/workspaces/ws-1/verify/repair/S2", json=_BODY)
        checks = _equiv_checks(eng)
        # Every equivalence_check written by the repair names ONLY S2.
        assert {ck.evidence_map.get("story_id") for ck in checks} == {"S2"}
    finally:
        app.dependency_overrides.clear()
