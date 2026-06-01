"""Enrich endpoints: inject stub enrichers so wiring + job + poll + response shaping
are exercised without a live LLM or Neo4j. Mirrors test_controlplane_blueprint_api.py
(SQLite engine, dependency_overrides, jobs.runner.inline, fake Neo4j factory)."""
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cobol_modernizer.api import app
from cobol_modernizer.controlplane import analysis, jobs
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.persistence.tables import Base, Workspace


class _FakeNeo4j:
    def run(self, query, **params):
        return []

    def close(self):
        pass


def _setup(monkeypatch):
    """Build a TestClient whose enrich background job runs inline against an in-memory
    SQLite session + a fake Neo4j. Returns the client; caller clears overrides."""
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
            yield ss
            ss.commit()
        finally:
            ss.close()

    fake = _FakeNeo4j()
    jobs.runner._jobs.clear()
    monkeypatch.setattr(jobs.runner, "inline", True)
    monkeypatch.setattr(jobs, "make_neo4j", lambda: fake)
    monkeypatch.setattr(analysis, "_known_refs", lambda neo, slug: {"P1"})
    app.dependency_overrides[get_session] = _ov
    app.dependency_overrides[get_neo4j] = lambda: fake
    return TestClient(app)


def test_seams_enrich_runs_and_polls(monkeypatch):
    c = _setup(monkeypatch)
    try:
        monkeypatch.setattr(analysis, "rank_candidates",
                            lambda *a, **k: [{"program": "P1", "score": {"weighted": 1.0}}])

        async def _fake(cands, known, **kw):
            return {"P1": {"program": "P1", "rationale": "why",
                           "cited_refs": ["P1"], "grounded": True}}
        monkeypatch.setattr(analysis, "enrich_seams", _fake)

        assert c.post("/api/workspaces/ws-1/seams/enrich").status_code == 202
        body = c.get("/api/workspaces/ws-1/seams/enrichment").json()
        assert body["status"] == "done"
        assert body["result"]["narratives"]["P1"]["rationale"] == "why"
    finally:
        app.dependency_overrides.clear()


def test_plan_enrich_runs_and_polls(monkeypatch):
    c = _setup(monkeypatch)
    try:
        monkeypatch.setattr(analysis, "rank_candidates",
                            lambda *a, **k: [{"program": "P1", "reads": [], "writes": [],
                                              "score": {"weighted": 1.0}}])

        async def _fake(stories, waves, known, **kw):
            return {"stories": {"S1": {"story_id": "S1", "description": "d"}},
                    "delivery": {"edge_rationale": {}, "wave_narrative": []}}
        monkeypatch.setattr(analysis, "enrich_plan", _fake)

        assert c.post("/api/workspaces/ws-1/plan/enrich").status_code == 202
        body = c.get("/api/workspaces/ws-1/plan/enrichment").json()
        assert body["status"] == "done"
        assert body["result"]["stories"]["S1"]["description"] == "d"
    finally:
        app.dependency_overrides.clear()
