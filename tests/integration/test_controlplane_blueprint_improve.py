from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cobol_modernizer.api import app
from cobol_modernizer.brd.schema import BRDResult, Rating, Strategy
from cobol_modernizer.controlplane import blueprint as bp, jobs
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.persistence.tables import Base, Workspace


class _FakeNeo4j:
    def __init__(self, has_brd=True):
        self.has_brd = has_brd

    def run(self, query, **params):
        if "ORDER BY b.version DESC" in query:   # get_latest
            return [{"b": {"version": 1, "html": "<html>v1</html>"}}] if self.has_brd else []
        return []

    def close(self):
        pass


def _improved(slug, instruction, **kw):
    return BRDResult(brd_id="b2", repo_id=slug, version=2, rating=Rating.high,
                     weighted_score=4.4, attempts=1, attempt_history=[],
                     model="claude-sonnet-4-6", strategy=Strategy.single_shot,
                     html_path="/tmp/v2.html", created_at=datetime.now(timezone.utc),
                     token_usage={})


def _setup(monkeypatch, has_brd=True):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Workspace(id="ws-1", name="m", repo_slug="demo", created_by="x"))
        s.commit()

    def _ov():
        ss = Session(eng)
        try:
            yield ss; ss.commit()
        finally:
            ss.close()

    fake = _FakeNeo4j(has_brd=has_brd)
    jobs.runner._jobs.clear()
    monkeypatch.setattr(jobs.runner, "inline", True)
    monkeypatch.setattr(jobs, "make_neo4j", lambda: fake)
    monkeypatch.setattr(bp, "improve_brd_graph_sync", _improved)
    app.dependency_overrides[get_session] = _ov
    app.dependency_overrides[get_neo4j] = lambda: fake
    return TestClient(app)


def test_improve_runs_and_polls(monkeypatch):
    c = _setup(monkeypatch)
    try:
        r = c.post("/api/workspaces/ws-1/blueprint/improve",
                   json={"instruction": "expand NFRs"})
        assert r.status_code == 202
        body = c.get("/api/workspaces/ws-1/blueprint/improve").json()
        assert body["status"] == "done"
        assert body["result"]["version"] == 2
    finally:
        app.dependency_overrides.clear()


def test_improve_400_on_empty_instruction(monkeypatch):
    c = _setup(monkeypatch)
    try:
        assert c.post("/api/workspaces/ws-1/blueprint/improve",
                      json={"instruction": "  "}).status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_improve_409_when_no_brd(monkeypatch):
    c = _setup(monkeypatch, has_brd=False)
    try:
        assert c.post("/api/workspaces/ws-1/blueprint/improve",
                      json={"instruction": "expand NFRs"}).status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_improve_status_idle_when_no_job(monkeypatch):
    c = _setup(monkeypatch)
    try:
        r = c.get("/api/workspaces/ws-1/blueprint/improve")
        assert r.status_code == 200
        assert r.json()["status"] == "idle"
    finally:
        app.dependency_overrides.clear()
