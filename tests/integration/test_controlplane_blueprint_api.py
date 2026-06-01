"""Blueprint (BRD) endpoint: inject a stub generator so the wiring, :Repository
MERGE, stage-marking, and response shaping are exercised without a live LLM.
The GET .../blueprint/html path is covered against a fake Neo4j returning a node."""
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from cobol_modernizer.brd.schema import BRDResult, Rating, Strategy
from cobol_modernizer.persistence.tables import Base, Workspace, JourneyStage
from cobol_modernizer.controlplane import blueprint as bp
from cobol_modernizer.controlplane import jobs
from cobol_modernizer.api import app
from cobol_modernizer.controlplane.deps import get_session, get_neo4j


class _FakeNeo4j:
    def __init__(self, entities=40):
        self.merged = []
        self.entities = entities

    def run(self, query, **params):
        if "count(n) AS c" in query:
            return [{"c": self.entities}]
        if "MERGE (r:Repository" in query:
            self.merged.append(params)
            return []
        if "RETURN b ORDER BY b.version DESC" in query:
            return [{"b": {"html": "<html><body>BRD v1</body></html>", "version": 1}}]
        return []


def _stub_brd(slug, *, client=None, repo_path=None, **kw):
    return BRDResult(
        brd_id="brd-1", repo_id=slug, version=1, rating=Rating.high,
        weighted_score=4.4, attempts=1, attempt_history=[], model="claude-sonnet-4-6",
        strategy=Strategy.map_reduce, html_path="/tmp/v1.html",
        created_at=datetime.now(timezone.utc),
        token_usage={"input": 1200, "output": 800, "cache_read": 0, "cache_creation": 0})


def _setup(monkeypatch, tmp_path, entities=40):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # source root with the repo dir present (run_blueprint 404s otherwise)
    (tmp_path / "carddemo-mini").mkdir()
    monkeypatch.setenv("COBOL_SOURCE_ROOT", str(tmp_path))
    # inject the stub generator in place of the real LLM pipeline
    monkeypatch.setattr(bp, "generate_brd_graph_sync", _stub_brd)

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Workspace(id="ws-1", name="m", repo_slug="carddemo-mini", created_by="x"))
        s.add(JourneyStage(id="stg-bp", workspace_id="ws-1", stage_key="blueprint",
                           ordinal=5, status="pending"))
        s.commit()

    def _ov():
        ss = Session(eng)
        try:
            yield ss; ss.commit()
        finally:
            ss.close()

    fake = _FakeNeo4j(entities=entities)
    # run the background job synchronously, building its own session/neo4j from
    # the test engine + fake (the real factories would hit Postgres/live Neo4j).
    jobs.runner._jobs.clear()
    monkeypatch.setattr(jobs.runner, "inline", True)
    monkeypatch.setattr(jobs, "make_session", lambda: Session(eng))
    monkeypatch.setattr(jobs, "make_neo4j", lambda: fake)
    app.dependency_overrides[get_session] = _ov
    app.dependency_overrides[get_neo4j] = lambda: fake
    return TestClient(app), eng, fake


def test_blueprint_runs_as_job_merges_repository_and_marks_stage(monkeypatch, tmp_path):
    c, eng, fake = _setup(monkeypatch, tmp_path)
    try:
        resp = c.post("/api/workspaces/ws-1/blueprint")
        assert resp.status_code == 202
        # inline runner -> job already finished by the time POST returns
        body = resp.json()
        assert body["status"] == "done"
        r = body["result"]
        assert r["brd_id"] == "brd-1" and r["rating"] == "high"
        assert r["version"] == 1 and r["strategy"] == "map_reduce"
        assert r["token_usage"]["input"] == 1200
        assert fake.merged and fake.merged[0]["slug"] == "carddemo-mini"
        # GET status reflects the finished job too
        st = c.get("/api/workspaces/ws-1/blueprint").json()
        assert st["status"] == "done" and st["result"]["brd_id"] == "brd-1"
        with Session(eng) as s:
            assert s.execute(select(JourneyStage.status).where(
                JourneyStage.stage_key == "blueprint")).scalar_one() == "passed"
    finally:
        app.dependency_overrides.clear()


def test_blueprint_status_reports_persisted_brd_when_no_job(monkeypatch, tmp_path):
    # no in-process job (e.g. after a restart) but a BRD exists in the graph store
    c, eng, fake = _setup(monkeypatch, tmp_path)
    try:
        st = c.get("/api/workspaces/ws-1/blueprint").json()
        assert st["status"] == "done" and st["result"]["version"] == 1
    finally:
        app.dependency_overrides.clear()


def test_blueprint_html_serves_latest(monkeypatch, tmp_path):
    c, eng, fake = _setup(monkeypatch, tmp_path)
    try:
        resp = c.get("/api/workspaces/ws-1/blueprint/html")
        assert resp.status_code == 200
        assert "BRD v1" in resp.text
    finally:
        app.dependency_overrides.clear()


def test_blueprint_503_without_api_key(monkeypatch, tmp_path):
    c, eng, fake = _setup(monkeypatch, tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    try:
        assert c.post("/api/workspaces/ws-1/blueprint").status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_blueprint_409_when_repo_not_parsed(monkeypatch, tmp_path):
    # empty graph for the repo -> fast 409 instead of a doomed multi-minute LLM run
    c, eng, fake = _setup(monkeypatch, tmp_path, entities=0)
    try:
        resp = c.post("/api/workspaces/ws-1/blueprint")
        assert resp.status_code == 409
        assert "Parse" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()
