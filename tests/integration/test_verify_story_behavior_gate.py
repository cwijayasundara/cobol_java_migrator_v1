import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cobol_modernizer.api import app
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.controlplane.verify import evaluate_story_behavior
from cobol_modernizer.persistence.tables import Artifact, Base, Gate, JourneyStage, Workspace


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = Session(eng)
    s.add(Workspace(id="ws-1", name="m", repo_slug="r", created_by="t"))
    s.add(JourneyStage(workspace_id="ws-1", stage_key="verify", ordinal=12, status="running"))
    s.commit()
    return s


def test_gate_passes_when_all_stories_have_tests_and_equivalence():
    s = _session()
    stories = [{"id": "US-1", "acceptance_criteria": [{"id": "AC-1"}]}]
    gate = evaluate_story_behavior(s, "ws-1", stories=stories,
                                   generated_test_refs=["AC-1"], equivalence_verdict="pass")
    s.flush()
    assert gate.status == "passed"


def test_gate_blocks_when_equivalence_failed():
    s = _session()
    stories = [{"id": "US-1", "acceptance_criteria": [{"id": "AC-1"}]}]
    gate = evaluate_story_behavior(s, "ws-1", stories=stories,
                                   generated_test_refs=["AC-1"], equivalence_verdict="fail")
    s.flush()
    assert gate.status == "open"
    assert "US-1" in str(gate.result)


def test_gate_blocks_when_acceptance_test_missing():
    s = _session()
    stories = [{"id": "US-1", "acceptance_criteria": [{"id": "AC-1"}]}]
    gate = evaluate_story_behavior(s, "ws-1", stories=stories,
                                   generated_test_refs=[], equivalence_verdict="pass")
    s.flush()
    assert gate.status == "open"
    assert "US-1" in str(gate.result)


# --- run_verify wiring (API level): backlog present + seeded test-refs artifact ---


class _FakeNeo4jWithBacklog:
    """Returns a backlog node (one story citing AC-1) for the get_latest query;
    no seam writers so equivalence stays clean."""

    def run(self, query, **params):
        if "HAS_BACKLOG" in query and "Backlog" in query:
            stories = [{"id": "US-1", "acceptance_criteria": [{"id": "AC-1"}]}]
            return [{"b": {"stories_json": json.dumps(stories)}}]
        return []


def _wiring_client():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Workspace(id="ws-1", name="m", repo_slug="carddemo-mini", created_by="x"))
        s.add(JourneyStage(id="stg-v", workspace_id="ws-1", stage_key="verify",
                           ordinal=12, status="pending"))
        s.add(Artifact(workspace_id="ws-1", kind="generated_test_refs", version=1,
                       object_uri="mem://refs", content_hash="h",
                       evidence_map={"acceptance_criteria": ["AC-1"]}))
        s.commit()

    def _ov():
        ss = Session(eng)
        try:
            yield ss
            ss.commit()
        finally:
            ss.close()

    app.dependency_overrides[get_session] = _ov
    app.dependency_overrides[get_neo4j] = lambda: _FakeNeo4jWithBacklog()
    return TestClient(app), eng


def test_run_verify_wiring_creates_story_behavior_gate():
    c, eng = _wiring_client()
    try:
        r = c.post("/api/workspaces/ws-1/verify", json={
            "program": "CBPOST1M", "record": "ACCT-RECORD", "record_key": "ID",
            "golden_records": [{"ID": "1", "BAL": "100.00"}],
            "candidate_records": [{"ID": "1", "BAL": "100.00"}],
        }).json()
        assert r["verdict"] == "pass"
        with Session(eng) as s:
            gate = s.execute(select(Gate).where(
                Gate.workspace_id == "ws-1", Gate.gate_key == "story_behavior")
            ).scalars().first()
            assert gate is not None
            assert gate.status == "passed"
    finally:
        app.dependency_overrides.clear()
