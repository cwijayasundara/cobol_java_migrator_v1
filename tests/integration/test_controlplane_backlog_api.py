import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cobol_modernizer.api import app
from cobol_modernizer.controlplane import jobs
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.enrichment.base import EnrichmentResult
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


def _fake_payload_dict():
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


def _fake_payload(**_kw):
    """A typed success result (the orchestrator's `EnrichmentResult` contract)."""
    return EnrichmentResult(payload=_fake_payload_dict(), ok=True, cause=None)


def _multi_epic_result():
    """A typed DECOMPOSED success result whose stories span multiple epics."""
    return EnrichmentResult(payload={
        "epics": [
            {"id": "EPIC-1", "title": "Posting", "outcome": "apply",
             "brd_requirement_ids": ["FR-1"], "story_ids": ["US-1"],
             "evidence_refs": ["CBPOST1M"]},
            {"id": "EPIC-2", "title": "Reporting", "outcome": "report",
             "brd_requirement_ids": ["FR-1"], "story_ids": ["US-2"],
             "evidence_refs": ["CBPOST1M"]},
        ],
        "stories": [
            {"id": "US-1", "epic_id": "EPIC-1", "title": "Post valid tx",
             "actor": "batch", "narrative": "As a batch I post.",
             "brd_requirement_ids": ["FR-1"],
             "acceptance_criteria": [{"id": "AC-1", "statement": "balance updates",
                                      "evidence_refs": ["CBPOST1M.2100-POST"]}],
             "evidence_refs": ["CBPOST1M", "CBPOST1M.2100-POST"]},
            {"id": "US-2", "epic_id": "EPIC-2", "title": "Report posted tx",
             "actor": "analyst", "narrative": "As an analyst I report.",
             "brd_requirement_ids": ["FR-1"],
             "acceptance_criteria": [{"id": "AC-2", "statement": "report lists tx",
                                      "evidence_refs": ["CBPOST1M.2100-POST"]}],
             "evidence_refs": ["CBPOST1M", "CBPOST1M.2100-POST"]},
        ],
    }, ok=True, cause=None)


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
    monkeypatch.setattr(bl, "generate_backlog_result",
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


def test_backlog_post_decomposed_multi_epic_persists_and_creates_gate(monkeypatch):
    """A typed DECOMPOSED success whose stories span multiple epics feeds the
    unchanged reduce: persists, derives the DAG, and publishes coverage gates."""
    from cobol_modernizer.controlplane import backlog as bl

    async def _gen(**_kw):
        return _multi_epic_result()

    monkeypatch.setattr(bl, "generate_backlog_result", _gen)
    client, eng = _client(monkeypatch)
    try:
        r = client.post("/api/workspaces/ws-1/backlog")
        assert r.status_code in (200, 202)
        done = client.get("/api/workspaces/ws-1/backlog").json()
        assert done["status"] == "done"
        assert done["result"]["epics"] == 2
        assert done["result"]["stories"] == 2
        with Session(eng) as s:
            gates = {g.gate_key: g for g in
                     s.execute(select(Gate).where(Gate.workspace_id == "ws-1")).scalars().all()}
            assert "backlog_coverage" in gates
            assert "brd_logic_coverage" in gates
    finally:
        app.dependency_overrides.clear()
        jobs.runner.inline = False


def test_backlog_post_typed_failure_surfaces_concrete_cause(monkeypatch):
    """A typed FAILURE from the orchestrator surfaces as a 502 whose error names the
    concrete cause — not the old generic string, not a runner-reconstructed guess."""
    from cobol_modernizer.controlplane import backlog as bl

    async def _fail(**_kw):
        return EnrichmentResult(payload={}, ok=False,
                                cause="epics generation failed: timeout after 120s")

    monkeypatch.setattr(bl, "generate_backlog_result", _fail)
    client, _ = _client(monkeypatch)
    try:
        r = client.post("/api/workspaces/ws-1/backlog")
        assert r.status_code in (200, 202)
        failed = client.get("/api/workspaces/ws-1/backlog").json()
        assert failed["status"] == "failed"
        assert failed["error"]
        assert "502" in failed["error"]
        assert "epics generation failed: timeout after 120s" in failed["error"]
    finally:
        app.dependency_overrides.clear()
        jobs.runner.inline = False


class _LargeGraphNeo4j(FakeNeo4j):
    """FakeNeo4j whose graph holds 1000 refs but whose BRD cites only a subset."""

    CITED = ["CBPOST1M", "CBPOST1M.2100-POST"]

    def run(self, query, **params):
        if "HAS_BRD" in query or "(b:BRD)" in query:
            return [{"b": {"version": 1,
                           "sections": json.dumps([{"title": "Functional",
                               "requirements": [{"id": "FR-1", "text": "Post tx",
                                                 "evidence_refs": self.CITED}]}]),
                           "evidence_map": "{}"}}]
        if "RETURN n.qualified_name AS q" in query or "RETURN n.qualified_name AS ref" in query:
            key = "q" if " AS q" in query else "ref"
            rows = [{key: "CBPOST1M", "kind": "Program"},
                    {key: "CBPOST1M.2100-POST", "kind": "Paragraph"}]
            rows += [{key: f"NOISE{i}", "kind": "Program"} for i in range(998)]
            return rows
        return super().run(query, **params)


def test_backlog_inlines_only_relevant_refs_but_grounds_full_set(monkeypatch):
    from cobol_modernizer.controlplane import backlog as bl

    captured: dict = {}

    async def _capture(**kw):
        captured["known_refs"] = list(kw["known_refs"])
        return _fake_payload()  # typed EnrichmentResult

    grounded: dict = {}
    real_parse = bl.parse_backlog_payload

    def _parse_spy(raw, *, repo_slug, known_refs, known_requirement_ids):
        grounded["known_refs"] = set(known_refs)
        return real_parse(raw, repo_slug=repo_slug, known_refs=known_refs,
                          known_requirement_ids=known_requirement_ids)

    monkeypatch.setattr(bl, "generate_backlog_result", _capture)
    monkeypatch.setattr(bl, "parse_backlog_payload", _parse_spy)

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
    monkeypatch.setattr(jobs, "make_neo4j", lambda: _LargeGraphNeo4j())
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_neo4j] = lambda: _LargeGraphNeo4j()
    client = TestClient(app)
    try:
        r = client.post("/api/workspaces/ws-1/backlog")
        assert r.status_code in (200, 202)
        # Prompt got ONLY the BRD-relevant subset — not the whole 1000, not a numeric slice.
        assert set(captured["known_refs"]) == set(_LargeGraphNeo4j.CITED)
        assert "NOISE0" not in captured["known_refs"]
        # Grounding ran against the FULL graph ref set (1000 refs).
        assert len(grounded["known_refs"]) == 1000
        assert "NOISE0" in grounded["known_refs"]
        assert set(_LargeGraphNeo4j.CITED).issubset(grounded["known_refs"])
    finally:
        app.dependency_overrides.clear()
        jobs.runner.inline = False


def test_backlog_post_surfaces_generation_failure(monkeypatch):
    from cobol_modernizer.controlplane import backlog as bl

    async def _boom(**_kw):
        raise RuntimeError("llm down")

    monkeypatch.setattr(bl, "generate_backlog_result", _boom)
    client, _ = _client(monkeypatch)
    try:
        r = client.post("/api/workspaces/ws-1/backlog")
        assert r.status_code in (200, 202)
        failed = client.get("/api/workspaces/ws-1/backlog").json()
        assert failed["status"] == "failed"
        assert failed["error"]
        assert "llm down" in failed["error"]
    finally:
        app.dependency_overrides.clear()
        jobs.runner.inline = False
