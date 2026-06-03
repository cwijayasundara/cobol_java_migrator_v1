"""Verify endpoint: runs the REAL deterministic equivalence engine on supplied
golden + candidate records, with seam-linking over a fake graph. Covers a pass,
a numeric-precision fail (seam-linked defect), and the no-golden 409. Also covers
the versioned `verify_report` Artifact persistence + the GET /verify/status read."""
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from cobol_modernizer.persistence.tables import Base, Workspace, JourneyStage, Artifact
from cobol_modernizer.api import app
from cobol_modernizer.controlplane.deps import get_session, get_neo4j


class _FakeNeo4j:
    def run(self, query, **params):
        if "WRITES|MOVES_TO" in query and params.get("field") == "BAL":
            return [{"qualified_name": "CBPOST1M.1300-POST", "edge": "MOVES_TO",
                     "file_path": "cbl/CBPOST1M.cbl"}]
        return []


def _client():
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

    app.dependency_overrides[get_session] = _ov
    app.dependency_overrides[get_neo4j] = lambda: _FakeNeo4j()
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
