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


class _StoreNeo4j:
    """Fake Neo4j that actually persists :Enrichment nodes (per-(repo,kind) versioning),
    so reuse / restart-safe GET / refresh can be exercised without a live graph."""
    def __init__(self):
        self.enr: list[dict] = []

    def run(self, query, **p):
        if "CREATE (e:Enrichment" in query:
            v = len([x for x in self.enr
                     if x["repo_slug"] == p["repo_slug"] and x["kind"] == p["kind"]]) + 1
            row = dict(p); row["version"] = v; self.enr.append(row)
            return [{"version": v}]
        if "ORDER BY e.version DESC" in query:
            rows = [x for x in self.enr
                    if x.get("repo_slug") == p.get("repo_slug") and x.get("kind") == p.get("kind")]
            return [{"e": rows[-1]}] if rows else []
        return []

    def close(self):
        pass


def test_enrich_persists_then_reuses_and_refresh_reruns(monkeypatch):
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

    fake = _StoreNeo4j()
    jobs.runner._jobs.clear()
    monkeypatch.setattr(jobs.runner, "inline", True)
    monkeypatch.setattr(jobs, "make_neo4j", lambda: fake)
    monkeypatch.setattr(analysis, "_known_refs", lambda neo, slug: {"P1"})
    monkeypatch.setattr(analysis, "rank_candidates",
                        lambda *a, **k: [{"program": "P1", "score": {"weighted": 1.0}}])
    calls = {"n": 0}

    async def _fake(cands, known, **kw):
        calls["n"] += 1
        return {"P1": {"program": "P1", "rationale": f"v{calls['n']}",
                       "cited_refs": ["P1"], "grounded": True}}
    monkeypatch.setattr(analysis, "enrich_seams", _fake)
    app.dependency_overrides[get_session] = _ov
    app.dependency_overrides[get_neo4j] = lambda: fake
    try:
        c = TestClient(app)
        # 1) first run computes once + persists
        assert c.post("/api/workspaces/ws-1/seams/enrich").status_code == 202
        assert calls["n"] == 1

        # 2) re-run WITHOUT refresh reuses the persisted result — no second LLM call
        jobs.runner._jobs.clear()  # simulate the in-memory job being gone (restart)
        r2 = c.post("/api/workspaces/ws-1/seams/enrich")
        assert r2.json()["status"] == "done"
        assert calls["n"] == 1
        assert r2.json()["result"]["narratives"]["P1"]["rationale"] == "v1"

        # 3) GET after a restart (no in-memory job) still returns the persisted result
        jobs.runner._jobs.clear()
        body = c.get("/api/workspaces/ws-1/seams/enrichment").json()
        assert body["status"] == "done"
        assert body["result"]["narratives"]["P1"]["rationale"] == "v1"

        # 4) refresh=true forces a fresh run
        assert c.post("/api/workspaces/ws-1/seams/enrich?refresh=true").status_code == 202
        assert calls["n"] == 2
    finally:
        app.dependency_overrides.clear()


def test_design_enrich_runs_and_polls(monkeypatch):
    c = _setup(monkeypatch)
    try:
        monkeypatch.setattr(analysis, "_compute_designs",
                            lambda neo, slug: [{"slice_id": "P1-slice",
                                                "owned_resources": ["R"],
                                                "evidence_map": {"DR-1": ["P1"]}}])

        async def _fake(designs, known, **kw):
            return {"P1-slice": {"slice_id": "P1-slice", "api_surface": "GET /x"}}
        monkeypatch.setattr(analysis, "enrich_design", _fake)

        assert c.post("/api/workspaces/ws-1/design/enrich").status_code == 202
        body = c.get("/api/workspaces/ws-1/design/enrichment").json()
        assert body["status"] == "done"
        assert body["result"]["narratives"]["P1-slice"]["api_surface"] == "GET /x"
    finally:
        app.dependency_overrides.clear()
