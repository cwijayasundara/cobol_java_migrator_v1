import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cobol_modernizer.api import app
from cobol_modernizer.controlplane import jobs
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.persistence.tables import Base, Gate, JourneyStage, Workspace


class FakeNeo4j:
    def __init__(self):
        self.backlog = None

    def run(self, query, **params):
        if "MERGE (r:Repository" in query:
            return []
        if "HAS_BRD" in query or "(b:BRD)" in query:
            return [{"b": {"version": 1,
                           "sections": json.dumps([{"title": "Functional",
                               "requirements": [{"id": "FR-1", "text": "Post tx"}]}]),
                           "evidence_map": "{}"}}]
        if "RETURN n.qualified_name AS q" in query or "RETURN n.qualified_name AS ref" in query:
            key = "q" if " AS q" in query else "ref"
            return [{key: "CBPOST1M", "kind": "Program"},
                    {key: "CBPOST1M.2100-POST", "kind": "Paragraph"}]
        if "all_programs" in query or "p.simple_name AS program" in query:
            return [{"program": "CBPOST1M"}]
        if "CREATE (b:Backlog" in query:
            self.backlog = dict(params, version=1)
            return [{"version": 1}]
        if "RETURN b ORDER BY b.version DESC" in query:
            return [{"b": self.backlog}] if self.backlog else []
        return []


def _fake_payload(**_kw):
    return {
        "epics": [{"id": "EPIC-1", "title": "Posting", "outcome": "apply",
                   "brd_requirement_ids": ["FR-1"], "story_ids": ["US-1"],
                   "evidence_refs": ["CBPOST1M"]}],
        "stories": [{"id": "US-1", "epic_id": "EPIC-1", "title": "Post valid tx",
                     "actor": "batch", "narrative": "As a batch I post.",
                     "brd_requirement_ids": ["FR-1"],
                     "acceptance_criteria": [{"id": "AC-1", "statement": "balance updates",
                                              "evidence_refs": ["CBPOST1M.2100-POST"]}],
                     "evidence_refs": ["CBPOST1M", "CBPOST1M.2100-POST"]}],
    }


def _client(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Workspace(id="ws-1", name="m", repo_slug="carddemo-mini", created_by="t"))
        s.add(JourneyStage(workspace_id="ws-1", stage_key="backlog", ordinal=6, status="running"))
        s.add(JourneyStage(workspace_id="ws-1", stage_key="blueprint", ordinal=5, status="passed"))
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
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_neo4j] = lambda: FakeNeo4j()
    return TestClient(app), eng


def test_backlog_status_idle_before_generation(monkeypatch):
    client, _ = _client(monkeypatch)
    try:
        r = client.get("/api/workspaces/ws-1/backlog")
        assert r.status_code == 200
        assert r.json()["status"] == "idle"
    finally:
        app.dependency_overrides.clear()
        jobs.runner.inline = False


def test_backlog_post_generates_persists_and_creates_gate(monkeypatch):
    from cobol_modernizer.controlplane import backlog as bl
    monkeypatch.setattr(bl, "generate_backlog_payload",
                        lambda **kw: __import__("asyncio").sleep(0, result=_fake_payload()))
    client, eng = _client(monkeypatch)
    try:
        r = client.post("/api/workspaces/ws-1/backlog")
        assert r.status_code in (200, 202)
        done = client.get("/api/workspaces/ws-1/backlog").json()
        assert done["status"] == "done"
        assert done["result"]["stories"] == 1
        with Session(eng) as s:
            gates = {g.gate_key: g for g in
                     s.execute(select(Gate).where(Gate.workspace_id == "ws-1")).scalars().all()}
            assert "backlog_coverage" in gates
            assert "brd_logic_coverage" in gates
    finally:
        app.dependency_overrides.clear()
        jobs.runner.inline = False
