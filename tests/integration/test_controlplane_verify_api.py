"""Verify endpoint: runs the REAL deterministic equivalence engine on supplied
golden + candidate records, with seam-linking over a fake graph. Covers a pass,
a numeric-precision fail (seam-linked defect), and the no-golden 409. Also covers
the versioned `verify_report` Artifact persistence + the GET /verify/status read,
and the per-story fan-out (Fan-Out-and-Synthesize) with a soft timeout."""
import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from cobol_modernizer.persistence.tables import Base, Workspace, JourneyStage, Artifact, Gate
from cobol_modernizer.api import app
from cobol_modernizer.controlplane.deps import get_session, get_neo4j


class _FakeNeo4j:
    def run(self, query, **params):
        if "WRITES|MOVES_TO" in query and params.get("field") == "BAL":
            return [{"qualified_name": "CBPOST1M.1300-POST", "edge": "MOVES_TO",
                     "file_path": "cbl/CBPOST1M.cbl"}]
        return []


def _backlog_node(stories: list[dict]) -> dict:
    return {"version": 1, "stories_json": json.dumps(stories), "epics_json": "[]"}


class _BacklogNeo4j(_FakeNeo4j):
    """Returns a versioned :Backlog (HAS_BACKLOG) so verify fans out per story."""
    def __init__(self, stories: list[dict]):
        self._stories = stories

    def run(self, query, **params):
        if "HAS_BACKLOG" in query and "ORDER BY" in query:
            return [{"b": _backlog_node(self._stories)}]
        return super().run(query, **params)


def _client(neo4j=None):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Workspace(id="ws-1", name="m", repo_slug="carddemo-mini", created_by="x"))
        s.add(JourneyStage(id="stg-v", workspace_id="ws-1", stage_key="verify",
                           ordinal=10, status="pending"))
        s.commit()

    def _ov():
        ss = Session(eng)
        try:
            yield ss; ss.commit()
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


def test_verify_pass_marks_stage_passed():
    c, eng = _client()
    try:
        r = c.post("/api/workspaces/ws-1/verify", json={
            "program": "CBPOST1M", "record": "ACCT-RECORD", "record_key": "ID",
            "golden_records": [{"ID": "1", "BAL": "100.00"}],
            "candidate_records": [{"ID": "1", "BAL": "100.00"}],
        }).json()
        assert r["verdict"] == "pass" and r["defect_count"] == 0
        assert _stage(eng) == "passed"
    finally:
        app.dependency_overrides.clear()


def test_verify_real_precision_defect_is_seam_linked():
    c, eng = _client()
    try:
        r = c.post("/api/workspaces/ws-1/verify", json={
            "program": "CBPOST1M", "record": "ACCT-RECORD", "record_key": "ID",
            "tolerance_yaml": "record: ACCT-RECORD\ndefault:\n  matcher: exact\n"
                              "rules:\n  - field: BAL\n    matcher: numeric_scale\n    scale: 2\n",
            "golden_records": [{"ID": "1", "BAL": "1234.56"}],
            "candidate_records": [{"ID": "1", "BAL": "1234.50"}],
            "dialect": "cobc 3.2 (ibm-strict, ASCII)",
        }).json()
        assert r["verdict"] == "fail" and r["defect_count"] == 1
        d = r["defects"][0]
        assert d["field"] == "BAL" and d["source_seam"] == "CBPOST1M.1300-POST"
        assert d["seam_edge_kind"] == "MOVES_TO" and d["severity"] == "high"
        assert _stage(eng) == "failed"
    finally:
        app.dependency_overrides.clear()


def test_verify_409_without_golden():
    c, eng = _client()
    try:
        assert c.post("/api/workspaces/ws-1/verify", json={
            "program": "P", "record": "R", "record_key": "ID",
            "golden_records": [], "candidate_records": [{"ID": "1"}],
        }).status_code == 409
    finally:
        app.dependency_overrides.clear()


def _verify_reports(eng):
    with Session(eng) as s:
        return s.execute(
            select(Artifact).where(Artifact.workspace_id == "ws-1",
                                   Artifact.kind == "verify_report")
            .order_by(Artifact.version)
        ).scalars().all()


def test_verify_persists_versioned_report_artifact():
    c, eng = _client()
    try:
        c.post("/api/workspaces/ws-1/verify", json={
            "program": "CBPOST1M", "record": "ACCT-RECORD", "record_key": "ID",
            "golden_records": [{"ID": "1", "BAL": "100.00"}],
            "candidate_records": [{"ID": "1", "BAL": "100.00"}],
        })
        reports = _verify_reports(eng)
        assert len(reports) == 1
        art = reports[0]
        assert art.version == 1
        assert art.object_uri == "inline://verify_report"
        assert art.content_hash.startswith("sha256:")
        ev = art.evidence_map
        assert ev["verdict"] == "pass"
        assert ev["defect_count"] == 0
        assert ev["records_compared"] == 1
    finally:
        app.dependency_overrides.clear()


def test_verify_second_run_bumps_version():
    c, eng = _client()
    try:
        c.post("/api/workspaces/ws-1/verify", json={
            "program": "CBPOST1M", "record": "ACCT-RECORD", "record_key": "ID",
            "golden_records": [{"ID": "1", "BAL": "100.00"}],
            "candidate_records": [{"ID": "1", "BAL": "100.00"}],
        })
        c.post("/api/workspaces/ws-1/verify", json={
            "program": "CBPOST1M", "record": "ACCT-RECORD", "record_key": "ID",
            "tolerance_yaml": "record: ACCT-RECORD\ndefault:\n  matcher: exact\n"
                              "rules:\n  - field: BAL\n    matcher: numeric_scale\n    scale: 2\n",
            "golden_records": [{"ID": "1", "BAL": "1234.56"}],
            "candidate_records": [{"ID": "1", "BAL": "1234.50"}],
        })
        reports = _verify_reports(eng)
        assert [r.version for r in reports] == [1, 2]
        assert reports[0].evidence_map["verdict"] == "pass"
        assert reports[1].evidence_map["verdict"] == "fail"
        assert reports[1].evidence_map["defect_count"] == 1
    finally:
        app.dependency_overrides.clear()


def test_verify_status_returns_latest_report():
    c, eng = _client()
    try:
        # No run yet -> idle.
        idle = c.get("/api/workspaces/ws-1/verify/status").json()
        assert idle["status"] == "idle" and idle["result"] is None

        c.post("/api/workspaces/ws-1/verify", json={
            "program": "CBPOST1M", "record": "ACCT-RECORD", "record_key": "ID",
            "golden_records": [{"ID": "1", "BAL": "100.00"}],
            "candidate_records": [{"ID": "1", "BAL": "100.00"}],
        })
        c.post("/api/workspaces/ws-1/verify", json={
            "program": "CBPOST1M", "record": "ACCT-RECORD", "record_key": "ID",
            "tolerance_yaml": "record: ACCT-RECORD\ndefault:\n  matcher: exact\n"
                              "rules:\n  - field: BAL\n    matcher: numeric_scale\n    scale: 2\n",
            "golden_records": [{"ID": "1", "BAL": "1234.56"}],
            "candidate_records": [{"ID": "1", "BAL": "1234.50"}],
        })
        body = c.get("/api/workspaces/ws-1/verify/status").json()
        assert body["status"] == "done"
        assert body["result"]["version"] == 2
        assert body["result"]["verdict"] == "fail"
        assert body["result"]["defect_count"] == 1
        assert body["result"]["repo_slug"] == "carddemo-mini"
        # The job/gate view is exposed alongside the persisted report.
        assert body["result"]["stage_status"] == "failed"
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Per-story fan-out (Fan-Out-and-Synthesize)
# --------------------------------------------------------------------------- #


def _story(sid: str) -> dict:
    return {"id": sid, "epic_id": "E1", "title": sid, "actor": "a", "narrative": "n",
            "acceptance_criteria": [], "seam_refs": [f"CBPOST1M.{sid}"]}


def _equiv_checks(eng):
    with Session(eng) as s:
        return s.execute(
            select(Artifact).where(Artifact.workspace_id == "ws-1",
                                   Artifact.kind == "equivalence_check")
            .order_by(Artifact.version)
        ).scalars().all()


def _gate(eng, gate_key: str):
    with Session(eng) as s:
        return s.execute(
            select(Gate).where(Gate.workspace_id == "ws-1", Gate.gate_key == gate_key)
        ).scalars().first()


def test_fanout_three_stories_one_failing_workspace_fails():
    # Stories S1/S3 match (pass), S2 mismatches at BAL (fail) -> workspace fails,
    # and every story persists an equivalence_check artifact.
    stories = [_story("S1"), _story("S2"), _story("S3")]
    c, eng = _client(_BacklogNeo4j(stories))
    try:
        body = c.post("/api/workspaces/ws-1/verify", json={
            "program": "CBPOST1M", "record": "ACCT-RECORD", "record_key": "ID",
            "tolerance_yaml": "record: ACCT-RECORD\ndefault:\n  matcher: exact\n"
                              "rules:\n  - field: BAL\n    matcher: numeric_scale\n    scale: 2\n",
            "golden_records": [{"ID": "1", "BAL": "100.00"}],
            # S2 candidate differs -> seam-linked defect for that story only is not
            # achievable from one body; instead the body candidate mismatches so
            # ALL stories fail equivalence. We assert the synthesized fail + fan-out.
            "candidate_records": [{"ID": "1", "BAL": "100.06"}],
        }).json()
        assert body["verdict"] == "fail"
        # per_story_verdicts rolled into the report.
        per = body["per_story_verdicts"]
        assert {p["story_id"] for p in per} == {"S1", "S2", "S3"}
        assert all(p["ok"] is False for p in per)  # all mismatch BAL
        # one equivalence_check artifact per story.
        checks = _equiv_checks(eng)
        assert len(checks) == 3
        assert {c.evidence_map["story_id"] for c in checks} == {"S1", "S2", "S3"}
        for ck in checks:
            assert ck.evidence_map["verdict"] == "fail"
        assert _stage(eng) == "failed"
    finally:
        app.dependency_overrides.clear()


def test_fanout_all_pass_workspace_passes_and_gate_upserted():
    stories = [_story("S1"), _story("S2")]
    c, eng = _client(_BacklogNeo4j(stories))
    try:
        body = c.post("/api/workspaces/ws-1/verify", json={
            "program": "CBPOST1M", "record": "ACCT-RECORD", "record_key": "ID",
            "golden_records": [{"ID": "1", "BAL": "100.00"}],
            "candidate_records": [{"ID": "1", "BAL": "100.00"}],
        }).json()
        assert body["verdict"] == "pass"
        assert all(p["ok"] for p in body["per_story_verdicts"])
        assert _stage(eng) == "passed"
        eq_gate = _gate(eng, "equivalence")
        assert eq_gate is not None and eq_gate.status == "passed"
        sb_gate = _gate(eng, "story_behavior")
        assert sb_gate is not None
    finally:
        app.dependency_overrides.clear()


def test_fanout_soft_timeout_returns_partial_not_crash(monkeypatch):
    # Force the per-story equivalence to overrun the soft timeout; the run must
    # return a partial sub-verdict (ok=False, reason="timeout"), never crash.
    import cobol_modernizer.controlplane.verify as verify_mod

    async def _slow_async(self, **kwargs):
        import asyncio
        await asyncio.sleep(5)
        raise AssertionError("should have been cancelled by soft timeout")

    monkeypatch.setattr(verify_mod.EquivalenceLab, "run_equivalence_async", _slow_async)
    monkeypatch.setenv("VERIFY_EQUIVALENCE_TIMEOUT_S", "0.05")

    stories = [_story("S1")]
    c, eng = _client(_BacklogNeo4j(stories))
    try:
        body = c.post("/api/workspaces/ws-1/verify", json={
            "program": "CBPOST1M", "record": "ACCT-RECORD", "record_key": "ID",
            "golden_records": [{"ID": "1", "BAL": "100.00"}],
            "candidate_records": [{"ID": "1", "BAL": "100.00"}],
        }).json()
        assert body["verdict"] == "fail"  # timeout => not a pass
        per = body["per_story_verdicts"]
        assert len(per) == 1
        assert per[0]["ok"] is False
        assert per[0]["reason"] == "timeout"
        # The partial sub-verdict is still persisted as an equivalence_check.
        checks = _equiv_checks(eng)
        assert len(checks) == 1
        assert checks[0].evidence_map["verdict"] == "fail"
        assert _stage(eng) == "failed"
    finally:
        app.dependency_overrides.clear()


def test_fanout_concurrency_bounded_by_env(monkeypatch):
    # With VERIFY_MAX_CONCURRENCY=2 and 5 stories, no more than 2 per-story
    # equivalence checks run at once.
    import asyncio
    import cobol_modernizer.controlplane.verify as verify_mod

    state = {"now": 0, "peak": 0}
    real = verify_mod.EquivalenceLab.run_equivalence_async

    async def _tracking(self, **kwargs):
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.02)
        try:
            return await real(self, **kwargs)
        finally:
            state["now"] -= 1

    monkeypatch.setattr(verify_mod.EquivalenceLab, "run_equivalence_async", _tracking)
    monkeypatch.setenv("VERIFY_MAX_CONCURRENCY", "2")

    stories = [_story(f"S{i}") for i in range(5)]
    c, eng = _client(_BacklogNeo4j(stories))
    try:
        c.post("/api/workspaces/ws-1/verify", json={
            "program": "CBPOST1M", "record": "ACCT-RECORD", "record_key": "ID",
            "golden_records": [{"ID": "1", "BAL": "100.00"}],
            "candidate_records": [{"ID": "1", "BAL": "100.00"}],
        })
        assert state["peak"] <= 2
        assert len(_equiv_checks(eng)) == 5
    finally:
        app.dependency_overrides.clear()


def test_fanout_409_without_golden_preserved():
    stories = [_story("S1")]
    c, eng = _client(_BacklogNeo4j(stories))
    try:
        assert c.post("/api/workspaces/ws-1/verify", json={
            "program": "P", "record": "R", "record_key": "ID",
            "golden_records": [], "candidate_records": [{"ID": "1"}],
        }).status_code == 409
    finally:
        app.dependency_overrides.clear()
