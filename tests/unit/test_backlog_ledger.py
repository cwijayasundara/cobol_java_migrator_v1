import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from cobol_modernizer.controlplane.backlog import (
    _generate_backlog_with_ledger,
    _pack_for_epics_unit,
    _pack_for_stories_unit,
)
from cobol_modernizer.enrichment.refs import relevant_refs
from cobol_modernizer.persistence.repo import PgRepo
from cobol_modernizer.persistence.tables import Base


SECTIONS = [
    {"title": "Posting", "requirements": [{"id": "FR-1", "text": "Post tx"}]},
    {"title": "Reporting", "requirements": [{"id": "FR-2", "text": "Report tx"}]},
]
EVIDENCE = {"FR-1": ["CBPOST1M"], "FR-2": ["CBRPT1M"]}
KNOWN_REFS = ["CBPOST1M", "CBRPT1M"]
KNOWN_REQ_IDS = ["FR-1", "FR-2"]


class _Runner:
    def __init__(self):
        self.calls = []
        self.token_usage = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
        self.cost_usd = 0.0

    async def run_structured(self, **kw):
        self.calls.append(kw)
        if kw.get("label") == "backlog-epics":
            return {"epics": [
                {"id": "EPIC-1", "title": "Posting", "outcome": "post",
                 "brd_requirement_ids": ["FR-1"], "story_ids": ["US-1"],
                 "evidence_refs": ["CBPOST1M"]},
                {"id": "EPIC-2", "title": "Reporting", "outcome": "report",
                 "brd_requirement_ids": ["FR-2"], "story_ids": ["US-2"],
                 "evidence_refs": ["CBRPT1M"]},
            ]}
        if '"id": "EPIC-2"' in kw["prompt"]:
            return {"stories": [{
                "id": "US-2", "epic_id": "EPIC-2", "title": "Report tx",
                "actor": "analyst", "narrative": "As an analyst I report.",
                "brd_requirement_ids": ["FR-2"],
                "acceptance_criteria": [{"id": "AC-2", "statement": "Then tx is listed",
                                         "evidence_refs": ["CBRPT1M"]}],
                "evidence_refs": ["CBRPT1M"],
            }]}
        return {"stories": [{
            "id": "US-1", "epic_id": "EPIC-1", "title": "Post tx",
            "actor": "operator", "narrative": "As an operator I post.",
            "brd_requirement_ids": ["FR-1"],
            "acceptance_criteria": [{"id": "AC-1", "statement": "Then tx is posted",
                                     "evidence_refs": ["CBPOST1M"]}],
            "evidence_refs": ["CBPOST1M"],
        }]}


def test_backlog_ledger_records_units_and_reuses_cache(monkeypatch):
    monkeypatch.setenv("BACKLOG_GEN_MODE", "decomposed")
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        repo = PgRepo(s)
        ws = repo.create_workspace(name="sample", repo_slug="repo", created_by="x")
        run = repo.start_run(workspace_id=ws.id, stage_id=None, role="backlog",
                             model="m", started_by="x")
        runner = _Runner()

        result = asyncio.run(_generate_backlog_with_ledger(
            runner=runner, model="m", timeout_s=5, max_turns=4,
            brd_sections=SECTIONS, known_refs=KNOWN_REFS,
            brd_evidence_map=EVIDENCE, known_requirement_ids=KNOWN_REQ_IDS,
            ledger=repo, workspace_id=ws.id, repo_slug=ws.repo_slug,
            agent_run_id=run.id))

        assert result.ok
        assert {s["id"] for s in result.payload["stories"]} == {"US-1", "US-2"}
        units = repo.list_work_units(workspace_id=ws.id, stage="backlog")
        assert {(u.unit_type, u.unit_key, u.status) for u in units} == {
            ("epics", "epics", "succeeded"),
            ("stories", "initial:EPIC-1", "succeeded"),
            ("stories", "initial:EPIC-2", "succeeded"),
        }
        by_key = {(u.unit_type, u.unit_key): u for u in units}
        assert by_key[("epics", "epics")].input_hash == _pack_for_epics_unit(
            brd_sections=SECTIONS, known_refs=KNOWN_REFS,
            brd_evidence_map=EVIDENCE,
            known_requirement_ids=KNOWN_REQ_IDS).input_hash
        brd_relevant = relevant_refs(EVIDENCE, KNOWN_REFS) or KNOWN_REFS
        assert by_key[("stories", "initial:EPIC-1")].input_hash == (
            _pack_for_stories_unit(
                epic=result.payload["epics"][0], req_ids={"FR-1"},
                brd_sections=SECTIONS, known_refs=KNOWN_REFS,
                brd_evidence_map=EVIDENCE, brd_relevant=brd_relevant,
                known_requirement_ids=KNOWN_REQ_IDS,
                round_key="initial").input_hash)
        assert len(runner.calls) == 3

        cached_runner = _Runner()
        cached = asyncio.run(_generate_backlog_with_ledger(
            runner=cached_runner, model="m", timeout_s=5, max_turns=4,
            brd_sections=SECTIONS, known_refs=KNOWN_REFS,
            brd_evidence_map=EVIDENCE, known_requirement_ids=KNOWN_REQ_IDS,
            ledger=repo, workspace_id=ws.id, repo_slug=ws.repo_slug,
            agent_run_id=run.id))
        assert cached.ok
        assert {s["id"] for s in cached.payload["stories"]} == {"US-1", "US-2"}
        assert cached_runner.calls == []


def test_backlog_ledger_uses_deterministic_fast_path_by_default(monkeypatch):
    monkeypatch.delenv("BACKLOG_GEN_MODE", raising=False)
    monkeypatch.delenv("BACKLOG_DETERMINISTIC_FIRST", raising=False)
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        repo = PgRepo(s)
        ws = repo.create_workspace(name="sample", repo_slug="repo", created_by="x")
        runner = _Runner()

        result = asyncio.run(_generate_backlog_with_ledger(
            runner=runner, model="m", timeout_s=5, max_turns=4,
            brd_sections=SECTIONS, known_refs=KNOWN_REFS,
            brd_evidence_map=EVIDENCE, known_requirement_ids=KNOWN_REQ_IDS,
            ledger=repo, workspace_id=ws.id, repo_slug=ws.repo_slug,
            agent_run_id=None))

        assert result.ok
        assert {story["id"] for story in result.payload["stories"]} == {
            "US-FR-1", "US-FR-2"}
        assert runner.calls == []
        units = repo.list_work_units(workspace_id=ws.id, stage="backlog")
        assert [(u.unit_type, u.unit_key, u.status, u.model) for u in units] == [
            ("deterministic", "backlog", "succeeded", "deterministic")
        ]

        cached = asyncio.run(_generate_backlog_with_ledger(
            runner=runner, model="m", timeout_s=5, max_turns=4,
            brd_sections=SECTIONS, known_refs=KNOWN_REFS,
            brd_evidence_map=EVIDENCE, known_requirement_ids=KNOWN_REQ_IDS,
            ledger=repo, workspace_id=ws.id, repo_slug=ws.repo_slug,
            agent_run_id=None))
        assert cached.ok
        assert runner.calls == []


def test_backlog_ledger_records_failed_story_unit(monkeypatch):
    monkeypatch.setenv("BACKLOG_GEN_MODE", "decomposed")

    class _FailingStoryRunner(_Runner):
        async def run_structured(self, **kw):
            self.calls.append(kw)
            if kw.get("label") == "backlog-epics":
                return {"epics": [{"id": "EPIC-1", "title": "Posting",
                                   "outcome": "post",
                                   "brd_requirement_ids": ["FR-1"],
                                   "evidence_refs": ["CBPOST1M"]}]}
            return {}

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        repo = PgRepo(s)
        ws = repo.create_workspace(name="sample", repo_slug="repo", created_by="x")
        result = asyncio.run(_generate_backlog_with_ledger(
            runner=_FailingStoryRunner(), model="m", timeout_s=5, max_turns=4,
            brd_sections=SECTIONS[:1], known_refs=KNOWN_REFS,
            brd_evidence_map={"FR-1": ["CBPOST1M"]},
            known_requirement_ids=["FR-1"], ledger=repo,
            workspace_id=ws.id, repo_slug=ws.repo_slug, agent_run_id=None))

        assert not result.ok
        units = repo.list_work_units(workspace_id=ws.id, stage="backlog")
        assert {(u.unit_type, u.unit_key, u.status) for u in units} == {
            ("epics", "epics", "succeeded"),
            ("stories", "initial:EPIC-1", "failed"),
        }
