from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cobol_modernizer.api import app
from cobol_modernizer.controlplane import analysis as an, jobs
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.persistence.tables import Base, Gate, Workspace


class _FakeNeo4j:
    def run(self, query, **params):
        return []

    def close(self):
        pass


_STUB = {"repo_slug": "demo", "version": 1, "rating": "good",
         "contexts": [{"name": "Accounts"}], "designs": [{"slice_id": "X-slice"}],
         "quality": {"score": 1.0}, "quality_passed": True,
         "quality_threshold": {"minimum_score": 0.85},
         "token_usage": {}}


def _setup(monkeypatch, *, api_key: bool = False, return_engine: bool = False):
    if api_key:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    else:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
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
    client = TestClient(app)
    if return_engine:
        return client, eng
    return client


def test_domain_design_start_returns_202(monkeypatch):
    c = _setup(monkeypatch)
    try:
        r = c.post("/api/workspaces/ws-1/domain-design")
        assert r.status_code == 202
        assert r.json()["status"] == "done"  # inline runner finished
        assert r.json()["result"]["version"] == 1
        assert r.json()["result"]["quality_passed"] is True
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


def test_domain_design_status_includes_quality_gate(monkeypatch):
    c, eng = _setup(monkeypatch, return_engine=True)
    monkeypatch.setattr(
        an.DomainDesignStorage,
        "get_latest",
        lambda self, repo_slug: {
            "version": 2,
            "rating": "good",
            "contexts_json": '[{"name":"Accounts"}]',
            "designs_json": '[{"slice_id":"Accounts-slice"}]',
        },
    )
    with Session(eng) as s:
        s.add(Gate(
            workspace_id="ws-1",
            gate_key="domain_quality",
            status="passed",
            result={"context_count": 1, "anemic_aggregates": []},
            threshold={"anemic_aggregates": 0},
        ))
        s.commit()
    try:
        r = c.get("/api/workspaces/ws-1/domain-design")
        assert r.status_code == 200
        payload = r.json()["result"]
        assert payload["quality_passed"] is True
        assert payload["quality"]["context_count"] == 1
        assert payload["quality_gate"]["gate_key"] == "domain_quality"
    finally:
        app.dependency_overrides.clear()


def test_domain_design_refine_runs(monkeypatch):
    c = _setup(monkeypatch, api_key=True)
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
