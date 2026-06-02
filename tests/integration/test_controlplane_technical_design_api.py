import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cobol_modernizer.api import app
from cobol_modernizer.controlplane import jobs
from cobol_modernizer.controlplane import technical_design as td
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.persistence.tables import Base, Gate, JourneyStage, Workspace


class FakeNeo4j:
    def __init__(self):
        self.saved = None

    def run(self, query, **params):
        if "(d:DomainDesign)" in query or "HAS_DOMAIN_DESIGN" in query:
            return [{"d": {"version": 1, "contexts_json": json.dumps([{
                "name": "Posting",
                "member_programs": ["CBPOST1M"],
                "owned_resources": ["ACCTFILE"],
                "topology": {"deployment": "module"},
            }]),
                           "designs_json": "[]"}}]
        if "(b:Backlog)" in query or "HAS_BACKLOG" in query:
            return [{"b": {"version": 1, "stories_json": json.dumps([{
                "id": "US-1",
                "title": "Post card transaction",
                "context": "Posting",
                "evidence_refs": ["CBPOST1M"],
            }]),
                           "epics_json": "[]"}}]
        if "RETURN n.qualified_name AS q" in query:
            return [{"q": "CBPOST1M"}]
        if "CREATE (t:TechnicalDesign" in query:
            self.saved = dict(params, version=1)
            return [{"version": 1}]
        if "RETURN t ORDER BY t.version DESC" in query:
            return [{"t": self.saved}] if self.saved else []
        return []


def _payload(**_kw):
    import asyncio
    return asyncio.sleep(0, result={"services": [
        {"name": "posting-service", "bounded_context": "Posting", "deployment": "module",
         "story_ids": ["US-1"], "evidence_refs": ["CBPOST1M"],
         "persistence": [{"resource": "ACCTFILE", "access_pattern": "legacy-mimic"}]}]})


def _client(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Workspace(id="ws-1", name="m", repo_slug="carddemo-mini", created_by="t"))
        s.add(JourneyStage(workspace_id="ws-1", stage_key="design", ordinal=10, status="running"))
        s.commit()

    def session_override():
        ss = Session(eng)
        try:
            yield ss
        finally:
            ss.close()

    jobs.runner.inline = True
    monkeypatch.setattr(jobs, "make_session", lambda: Session(eng))
    monkeypatch.setattr(jobs, "make_neo4j", lambda: FakeNeo4j())
    monkeypatch.setattr(td, "generate_technical_design_payload", _payload)
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_neo4j] = lambda: FakeNeo4j()
    return TestClient(app), eng


def test_technical_design_post_persists_and_gates(monkeypatch):
    client, eng = _client(monkeypatch)
    try:
        r = client.post("/api/workspaces/ws-1/technical-design")
        assert r.status_code in (200, 202)
        done = client.get("/api/workspaces/ws-1/technical-design").json()
        assert done["status"] == "done"
        assert done["result"]["services"] == 1
        with Session(eng) as s:
            gates = {g.gate_key for g in
                     s.execute(select(Gate).where(Gate.workspace_id == "ws-1")).scalars().all()}
            assert "design_data_ownership" in gates
    finally:
        app.dependency_overrides.clear()
        jobs.runner.inline = False


def _empty_payload(**_kw):
    import asyncio
    return asyncio.sleep(0, result={})


def test_technical_design_empty_payload_uses_deterministic_fallback(monkeypatch):
    # run_batched returns {} on an LLM error/timeout/turn-cap, including external
    # billing failures. The stage should still produce a conservative graph-grounded
    # design so migration planning remains usable without another model call.
    client, eng = _client(monkeypatch)
    monkeypatch.setattr(td, "generate_technical_design_payload", _empty_payload)
    jobs.runner._jobs.pop(("technical_design", "ws-1"), None)
    try:
        client.post("/api/workspaces/ws-1/technical-design")
        done = client.get("/api/workspaces/ws-1/technical-design").json()
        assert done["status"] == "done"
        assert done["result"]["services"] == 1
        assert done["result"]["generation_mode"] == "deterministic_fallback"
        with Session(eng) as s:
            saved = s.execute(select(Gate).where(Gate.workspace_id == "ws-1")).scalars().all()
            assert {g.gate_key for g in saved} == {"design_data_ownership"}
    finally:
        app.dependency_overrides.clear()
        jobs.runner.inline = False


def test_technical_design_status_idle_before_generation(monkeypatch):
    client, _eng = _client(monkeypatch)
    jobs.runner._jobs.pop(("technical_design", "ws-1"), None)
    try:
        r = client.get("/api/workspaces/ws-1/technical-design")
        assert r.status_code == 200
        assert r.json()["status"] == "idle"
    finally:
        app.dependency_overrides.clear()
        jobs.runner.inline = False


class FakeNeo4jNoDomain(FakeNeo4j):
    def run(self, query, **params):
        if "(d:DomainDesign)" in query or "HAS_DOMAIN_DESIGN" in query:
            return []
        return super().run(query, **params)


def test_technical_design_409_without_domain_design(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Workspace(id="ws-1", name="m", repo_slug="carddemo-mini", created_by="t"))
        s.add(JourneyStage(workspace_id="ws-1", stage_key="design", ordinal=10, status="running"))
        s.commit()

    def session_override():
        ss = Session(eng)
        try:
            yield ss
        finally:
            ss.close()

    jobs.runner.inline = True
    monkeypatch.setattr(jobs, "make_session", lambda: Session(eng))
    monkeypatch.setattr(jobs, "make_neo4j", lambda: FakeNeo4jNoDomain())
    monkeypatch.setattr(td, "generate_technical_design_payload", _payload)
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_neo4j] = lambda: FakeNeo4jNoDomain()
    try:
        client = TestClient(app)
        client.post("/api/workspaces/ws-1/technical-design")
        done = client.get("/api/workspaces/ws-1/technical-design").json()
        assert done["status"] == "failed"
        assert "domain design" in (done["error"] or "")
    finally:
        app.dependency_overrides.clear()
        jobs.runner.inline = False
