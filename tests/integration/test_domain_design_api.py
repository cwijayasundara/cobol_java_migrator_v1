from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cobol_modernizer.api import app
from cobol_modernizer.controlplane import analysis as an, jobs
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.persistence.tables import Base, Workspace


class _FakeNeo4j:
    def run(self, query, **params):
        return []

    def close(self):
        pass


_STUB = {"repo_slug": "demo", "version": 1, "rating": "good",
         "contexts": [{"name": "Accounts"}], "designs": [{"slice_id": "X-slice"}],
         "token_usage": {}}


def _setup(monkeypatch):
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

    fake = _FakeNeo4j()
    jobs.runner._jobs.clear()
    monkeypatch.setattr(jobs.runner, "inline", True)
    monkeypatch.setattr(jobs, "make_neo4j", lambda: fake)
    # Stub out the heavy run-and-persist so the route runs without Neo4j/Anthropic.
    monkeypatch.setattr(an, "_domain_run_and_persist",
                        lambda slug, *, wid=None, instruction="": dict(_STUB))
    app.dependency_overrides[get_session] = _ov
    app.dependency_overrides[get_neo4j] = lambda: fake
    return TestClient(app)


def test_domain_design_start_returns_202(monkeypatch):
    c = _setup(monkeypatch)
    try:
        r = c.post("/api/workspaces/ws-1/domain-design")
        assert r.status_code == 202
        assert r.json()["status"] == "done"  # inline runner finished
        assert r.json()["result"]["version"] == 1
    finally:
        app.dependency_overrides.clear()


def test_domain_design_status_returns_200_with_status_key(monkeypatch):
    c = _setup(monkeypatch)
    try:
        c.post("/api/workspaces/ws-1/domain-design")
        r = c.get("/api/workspaces/ws-1/domain-design")
        assert r.status_code == 200
        assert "status" in r.json()
    finally:
        app.dependency_overrides.clear()


def test_domain_design_refine_runs(monkeypatch):
    c = _setup(monkeypatch)
    try:
        r = c.post("/api/workspaces/ws-1/domain-design/refine",
                   json={"instruction": "split the billing context"})
        assert r.status_code == 202
        assert r.json()["status"] == "done"
    finally:
        app.dependency_overrides.clear()


def test_domain_design_refine_400_on_blank(monkeypatch):
    c = _setup(monkeypatch)
    try:
        assert c.post("/api/workspaces/ws-1/domain-design/refine",
                      json={"instruction": "  "}).status_code == 400
    finally:
        app.dependency_overrides.clear()
