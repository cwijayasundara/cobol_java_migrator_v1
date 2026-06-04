import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cobol_modernizer.api import app
from cobol_modernizer.controlplane import jobs
from cobol_modernizer.controlplane import technical_design as td
from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.enrichment.base import EnrichmentResult
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
    return asyncio.sleep(0, result=EnrichmentResult(payload={"services": [
        {"name": "posting-service", "bounded_context": "Posting", "deployment": "microservice",
         "story_ids": ["US-1"], "evidence_refs": ["CBPOST1M"],
         "api_contracts": [{"name": "post-transaction", "method": "POST",
                            "path": "/api/posting/post-transaction"}],
         "persistence": [{"resource": "ACCTFILE", "access_pattern": "legacy-mimic"}]}]},
        ok=True, cause=None))


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
    monkeypatch.setattr(td, "generate_technical_design_result", _payload)
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
        assert done["result"]["quality_passed"] is True
        assert done["result"]["target_platform"]["spring_boot_version"].startswith("4.")
        assert "flowchart LR" in done["result"]["mermaid_component_diagram"]
        assert done["result"]["database_design"][0]["tables"][0]["table"] == "acctfile"
        with Session(eng) as s:
            gates = {g.gate_key for g in
                     s.execute(select(Gate).where(Gate.workspace_id == "ws-1")).scalars().all()}
            assert "design_data_ownership" in gates
            assert "technical_design_quality" in gates
    finally:
        app.dependency_overrides.clear()
        jobs.runner.inline = False


def _empty_payload(**_kw):
    import asyncio
    return asyncio.sleep(0, result=EnrichmentResult(
        payload={}, ok=False, cause="no output (turn cap / parse / api error)"))


def test_technical_design_empty_payload_uses_deterministic_fallback(monkeypatch):
    # The typed orchestrator returns ok=False on an LLM error/timeout/turn-cap,
    # including external billing failures. The stage should still produce a
    # conservative graph-grounded design so migration planning remains usable
    # without another model call — AND surface the concrete typed cause.
    client, eng = _client(monkeypatch)
    monkeypatch.setattr(td, "generate_technical_design_result", _empty_payload)
    jobs.runner._jobs.pop(("technical_design", "ws-1"), None)
    try:
        client.post("/api/workspaces/ws-1/technical-design")
        done = client.get("/api/workspaces/ws-1/technical-design").json()
        assert done["status"] == "incomplete"
        assert done["result"]["services"] == 1
        assert done["result"]["stage_status"] == "incomplete"
        assert done["result"]["generation_mode"] == "deterministic_fallback"
        # The typed cause from the orchestrator is surfaced (not swallowed).
        assert "no output" in (done["result"]["generation_cause"] or "")
        with Session(eng) as s:
            saved = s.execute(select(Gate).where(Gate.workspace_id == "ws-1")).scalars().all()
            by_key = {g.gate_key: g.status for g in saved}
            assert by_key == {
                "design_generation_complete": "open",
                "design_data_ownership": "passed",
                "technical_design_quality": "passed",
            }
    finally:
        app.dependency_overrides.clear()
        jobs.runner.inline = False


def test_no_ref_truncation_in_controlplane_source():
    # HARD CONSTRAINT: the old `sorted(known_refs)[:200]` truncation must be GONE.
    # The control plane now hands the FULL known_refs to the typed orchestrator, which
    # does lossless per-context relevance scoping (in the generator module).
    import inspect

    from cobol_modernizer.technical_design import generator as gen

    src = inspect.getsource(td)
    assert "[:200]" not in src
    gen_src = inspect.getsource(gen)
    assert "[:200]" not in gen_src
    assert "relevant_refs(" in gen_src  # lossless relevance scoping (no cap)


class FakeNeo4jManyRefs(FakeNeo4j):
    """A repo whose context cites >200 graph refs (the old [:200] would drop them)."""

    REFS = [f"CBREF{i:04d}" for i in range(250)]

    def run(self, query, **params):
        if "(d:DomainDesign)" in query or "HAS_DOMAIN_DESIGN" in query:
            return [{"d": {"version": 1, "contexts_json": json.dumps([{
                "name": "Posting",
                "member_programs": self.REFS,
                "owned_resources": ["ACCTFILE"],
                "topology": {"deployment": "module"},
            }]), "designs_json": "[]"}}]
        if "RETURN n.qualified_name AS q" in query:
            return [{"q": r} for r in self.REFS]
        return super().run(query, **params)


def test_all_relevant_refs_inlined_no_truncation(monkeypatch):
    # End-to-end: a context citing 250 refs must have ALL of them reach the typed
    # orchestrator (which does lossless per-context relevance) — nothing dropped by a
    # 200-cap. The control plane passes the FULL known_refs (no [:200] slice).
    captured = {}

    def _capture(**kw):
        import asyncio
        captured["known_refs"] = list(kw.get("known_refs") or [])
        captured["contexts"] = kw.get("contexts")
        return asyncio.sleep(0, result=EnrichmentResult(payload={"services": [
            {"name": "posting-service", "bounded_context": "Posting",
             "deployment": "microservice",
             "api_contracts": [{"name": "post", "method": "POST", "path": "/api/posting"}],
             "story_ids": ["US-1"]}]}, ok=True, cause=None))

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
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
    jobs.runner._jobs.pop(("technical_design", "ws-1"), None)
    monkeypatch.setattr(jobs, "make_session", lambda: Session(eng))
    monkeypatch.setattr(jobs, "make_neo4j", lambda: FakeNeo4jManyRefs())
    monkeypatch.setattr(td, "generate_technical_design_result", _capture)
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_neo4j] = lambda: FakeNeo4jManyRefs()
    try:
        client = TestClient(app)
        client.post("/api/workspaces/ws-1/technical-design")
        client.get("/api/workspaces/ws-1/technical-design")
        # full known_refs passed for lossless relevance scoping + grounding (no cap)
        assert set(FakeNeo4jManyRefs.REFS).issubset(set(captured["known_refs"]))
        assert len(captured["known_refs"]) >= 250
        # and the orchestrator, given these contexts, would inline ALL 250 (lossless)
        from cobol_modernizer.technical_design.generator import build_service_prompt
        from cobol_modernizer.enrichment.refs import relevant_refs as _rr
        ctx = captured["contexts"][0]
        refs = _rr(ctx, captured["known_refs"])
        prompt = build_service_prompt(
            context=ctx, backlog_json="{}", seam_waves_json="[]",
            relevant_refs=refs, known_story_ids=[])
        for r in FakeNeo4jManyRefs.REFS:
            assert r in prompt
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
    monkeypatch.setattr(td, "generate_technical_design_result", _payload)
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
