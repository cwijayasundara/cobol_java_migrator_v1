from cobol_modernizer.controlplane.domain import (
    _pack_for_decomposition,
    _pack_for_tactical_unit,
    run_domain_design,
)
import asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from cobol_modernizer.controlplane.analysis import _has_blocking_work_units
from cobol_modernizer.persistence.repo import PgRepo
from cobol_modernizer.persistence.tables import Base


class _StubClient:
    def run(self, query, **params):
        if "// writers" in query or "WRITES]->(x:CodeEntity)" in query:
            return [{"program": "P1", "writes": ["R1"]}, {"program": "P2", "writes": ["R2"]}]
        if "// cross_reads" in query:
            return [{"reader": "P2", "resource": "R1", "writer": "P1"}]
        if "RETURN n.qualified_name AS q" in query:
            return [{"q": "P1"}, {"q": "P2"}]
        return []


def _signals(client, *, repo, program):
    from cobol_modernizer.seam.schema import SeamSignals
    return SeamSignals(business=0.8, isolation=0.8, testability=0.8,
                       data_ownership=0.8, risk=0.1)


class _Runner:
    def __init__(self):
        self.calls = []
        self.token_usage = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
        self.cost_usd = 0.0

    async def run_structured(self, **kw):
        self.calls.append(kw)
        if "domain-decompose" in kw.get("label", ""):
            return {"contexts": [
                {"name": "Acct", "business_capability": "a", "member_programs": ["P1"],
                 "owned_resources": ["R1"], "depends_on": [], "cited_refs": ["P1"]},
                {"name": "Tx", "business_capability": "t", "member_programs": ["P2"],
                 "owned_resources": ["R2"], "depends_on": [], "cited_refs": ["P2"]}],
                "unassigned_programs": [], "cited_refs": []}
        if "domain-contract" in kw.get("label", ""):
            return {"repositories": ["R1Repository"], "domain_events": ["Changed"],
                    "api_surface": "GET /x", "cited_refs": ["P1"]}
        if "domain-mapping" in kw.get("label", ""):
            return {"cobol_mapping": [{"cobol_ref": "P1", "maps_to": "Agg.m",
                                       "note": "mapped"}],
                    "cited_refs": ["P1"]}
        return {"aggregates": [{"name": "Agg", "root_entity": "E", "invariants": ["i"],
                                "methods": ["m"]}], "value_objects": ["V"],
                "domain_services": ["S"], "cited_refs": ["P1"]}


def test_run_domain_design_end_to_end(monkeypatch):
    monkeypatch.setenv("DOMAIN_DESIGN_MODE", "llm")
    dd = run_domain_design(_StubClient(), "repo", brd_text="BRD", runner=_Runner(),
                           model="m", timeout_s=5, signals_fn=_signals)
    assert {c.name for c in dd.contexts} == {"Acct", "Tx"}
    assert len(dd.designs) == 2
    assert dd.rating in {"high", "medium", "low"}


def test_run_domain_design_records_work_units_and_reuses_cache(monkeypatch):
    monkeypatch.setenv("DOMAIN_DESIGN_MODE", "llm")
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        repo = PgRepo(s)
        ws = repo.create_workspace(name="sample", repo_slug="repo", created_by="x")
        run = repo.start_run(workspace_id=ws.id, stage_id=None, role="domain-design",
                             model="m", started_by="x")
        runner = _Runner()

        dd = run_domain_design(
            _StubClient(), "repo", brd_text="BRD", runner=runner,
            model="m", timeout_s=5, signals_fn=_signals, ledger=repo,
            workspace_id=ws.id, agent_run_id=run.id)

        assert len(dd.designs) == 2
        units = repo.list_work_units(workspace_id=ws.id, stage="domain-design")
        assert {(u.unit_type, u.unit_key, u.status) for u in units} == {
            ("decomposition", "decompose", "succeeded"),
            ("tactical-aggregate", "Acct", "succeeded"),
            ("tactical-contract", "Acct", "succeeded"),
            ("tactical-mapping", "Acct", "succeeded"),
            ("tactical-aggregate", "Tx", "succeeded"),
            ("tactical-contract", "Tx", "succeeded"),
            ("tactical-mapping", "Tx", "succeeded"),
        }
        by_kind = {(u.unit_type, u.unit_key): u for u in units}
        assert by_kind[("decomposition", "decompose")].input_hash == (
            _pack_for_decomposition(repo_slug="repo", brd_text="BRD",
                                    backlog_json="").input_hash)
        acct_ctx = next(c for c in dd.contexts if c.name == "Acct")
        assert by_kind[("tactical-aggregate", "Acct")].input_hash == (
            _pack_for_tactical_unit(
                unit_type="tactical-aggregate", unit_key="Acct",
                context=acct_ctx.model_dump(mode="json"),
                known_refs={"P1", "P2"}).input_hash)
        first_call_count = len(runner.calls)
        cached_runner = _Runner()
        cached = run_domain_design(
            _StubClient(), "repo", brd_text="BRD", runner=cached_runner,
            model="m", timeout_s=5, signals_fn=_signals, ledger=repo,
            workspace_id=ws.id, agent_run_id=run.id)
        assert {c.name for c in cached.contexts} == {"Acct", "Tx"}
        assert len(cached.designs) == 2
        assert len(cached_runner.calls) == 0
        assert first_call_count == 7


def test_run_domain_design_uses_deterministic_fast_path_by_default(monkeypatch):
    monkeypatch.delenv("DOMAIN_DESIGN_MODE", raising=False)
    monkeypatch.delenv("DOMAIN_DETERMINISTIC_FIRST", raising=False)
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        repo = PgRepo(s)
        ws = repo.create_workspace(name="sample", repo_slug="repo", created_by="x")
        runner = _Runner()

        dd = run_domain_design(
            _StubClient(), "repo", brd_text="BRD", runner=runner,
            model="m", timeout_s=5, signals_fn=_signals, ledger=repo,
            workspace_id=ws.id, backlog_json='{"stories":[{"id":"US-1","title":"Post account","evidence_refs":["P1"]}]}')

        assert dd.contexts
        assert dd.designs
        assert runner.calls == []
        units = repo.list_work_units(workspace_id=ws.id, stage="domain-design")
        assert [(u.unit_type, u.unit_key, u.status, u.model) for u in units] == [
            ("deterministic", "domain-design", "succeeded", "deterministic")
        ]


def test_domain_blocking_work_unit_detection():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        repo = PgRepo(s)
        ws = repo.create_workspace(name="sample", repo_slug="repo", created_by="x")
        unit = repo.create_work_unit(
            workspace_id=ws.id, repo_slug=ws.repo_slug, stage="domain-design",
            unit_type="tactical-aggregate", unit_key="Acct", input_hash="h")
        repo.mark_work_unit_failed(unit.id, error_cause="turn cap")
        assert _has_blocking_work_units(repo, workspace_id=ws.id,
                                        stage="domain-design") is True


def test_run_domain_design_bounds_tactical_context_concurrency(monkeypatch):
    monkeypatch.setenv("DOMAIN_DESIGN_MODE", "llm")
    monkeypatch.setenv("DOMAIN_TACTICAL_MAX_CONCURRENCY", "1")

    class _ManyContextRunner(_Runner):
        def __init__(self):
            super().__init__()
            self.inflight = 0
            self.max_inflight = 0

        async def run_structured(self, **kw):
            self.calls.append(kw)
            label = kw.get("label", "")
            if "domain-decompose" in label:
                return {"contexts": [
                    {"name": "C1", "business_capability": "a", "member_programs": ["P1"],
                     "owned_resources": ["R1"], "depends_on": [], "cited_refs": ["P1"]},
                    {"name": "C2", "business_capability": "b", "member_programs": ["P2"],
                     "owned_resources": ["R2"], "depends_on": [], "cited_refs": ["P2"]}],
                    "unassigned_programs": [], "cited_refs": []}
            self.inflight += 1
            self.max_inflight = max(self.max_inflight, self.inflight)
            await asyncio.sleep(0)
            try:
                return await super().run_structured(**kw)
            finally:
                self.inflight -= 1

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        repo = PgRepo(s)
        ws = repo.create_workspace(name="sample", repo_slug="repo", created_by="x")
        run = repo.start_run(workspace_id=ws.id, stage_id=None, role="domain-design",
                             model="m", started_by="x")
        runner = _ManyContextRunner()
        run_domain_design(
            _StubClient(), "repo", brd_text="BRD", runner=runner,
            model="m", timeout_s=5, signals_fn=_signals, ledger=repo,
            workspace_id=ws.id, agent_run_id=run.id)
        assert runner.max_inflight == 1


def test_run_domain_design_tolerates_one_failed_tactical_context(monkeypatch):
    monkeypatch.setenv("DOMAIN_DESIGN_MODE", "llm")
    class _OneContextFailsRunner(_Runner):
        async def run_structured(self, **kw):
            self.calls.append(kw)
            label = kw.get("label", "")
            if "domain-decompose" in label:
                return {"contexts": [
                    {"name": "Good", "business_capability": "a",
                     "member_programs": ["P1"], "owned_resources": ["R1"],
                     "depends_on": [], "cited_refs": ["P1"]},
                    {"name": "Bad", "business_capability": "b",
                     "member_programs": ["P2"], "owned_resources": ["R2"],
                     "depends_on": [], "cited_refs": ["P2"]}],
                    "unassigned_programs": [], "cited_refs": []}
            if "domain-aggregate:Bad" in label:
                return {}
            return await super().run_structured(**kw)

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        repo = PgRepo(s)
        ws = repo.create_workspace(name="sample", repo_slug="repo", created_by="x")
        run = repo.start_run(workspace_id=ws.id, stage_id=None, role="domain-design",
                             model="m", started_by="x")
        dd = run_domain_design(
            _StubClient(), "repo", brd_text="BRD", runner=_OneContextFailsRunner(),
            model="m", timeout_s=5, signals_fn=_signals, ledger=repo,
            workspace_id=ws.id, agent_run_id=run.id)

        assert {c.name for c in dd.contexts} == {"Good", "Bad"}
        assert {d.context for d in dd.designs} == {"Good"}
        units = repo.list_work_units(workspace_id=ws.id, stage="domain-design")
        by_key = {(u.unit_type, u.unit_key): u for u in units}
        assert by_key[("tactical-aggregate", "Bad")].status == "failed"
        assert _has_blocking_work_units(repo, workspace_id=ws.id,
                                        stage="domain-design") is True
