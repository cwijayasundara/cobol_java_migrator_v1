import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from cobol_modernizer.controlplane.technical_design import (
    _generate_technical_design_with_ledger,
    _pack_for_service_unit,
)
from cobol_modernizer.persistence.repo import PgRepo
from cobol_modernizer.persistence.tables import Base


class _Runner:
    def __init__(self):
        self.calls = []
        self.token_usage = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
        self.cost_usd = 0.0

    async def run_structured(self, **kw):
        self.calls.append(kw)
        if kw.get("label") == "technical-design:Posting":
            ctx = "Posting"
            name = "posting-service"
        else:
            ctx = "Accounts"
            name = "accounts-service"
        return {"services": [{
            "name": name,
            "bounded_context": ctx,
            "deployment": "module",
            "evidence_refs": ["CBPOST1M" if ctx == "Posting" else "CBACCT1M"],
        }]}


def test_technical_design_ledger_records_service_units_and_reuses_cache():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    contexts = [
        {"name": "Posting", "member_programs": ["CBPOST1M"], "cited_refs": ["CBPOST1M"]},
        {"name": "Accounts", "member_programs": ["CBACCT1M"], "cited_refs": ["CBACCT1M"]},
    ]
    stories = [{"id": "US-1", "context": "Posting"}]
    known_refs = ["CBPOST1M", "CBACCT1M"]
    known_story_ids = ["US-1"]

    with Session(eng) as s:
        repo = PgRepo(s)
        ws = repo.create_workspace(name="sample", repo_slug="repo", created_by="x")
        run = repo.start_run(workspace_id=ws.id, stage_id=None,
                             role="technical-design", model="m", started_by="x")
        runner = _Runner()
        result = asyncio.run(_generate_technical_design_with_ledger(
            runner=runner, model="m", timeout_s=5, max_turns=4,
            contexts=contexts, stories=stories, seam_waves=[],
            known_refs=known_refs, known_story_ids=known_story_ids,
            ledger=repo, workspace_id=ws.id, repo_slug=ws.repo_slug,
            agent_run_id=run.id))

        assert result.ok
        assert {s["bounded_context"] for s in result.payload["services"]} == {
            "Posting", "Accounts"}
        units = repo.list_work_units(workspace_id=ws.id, stage="technical-design")
        assert {(u.unit_type, u.unit_key, u.status) for u in units} == {
            ("service", "Posting", "succeeded"),
            ("service", "Accounts", "succeeded"),
        }
        by_key = {u.unit_key: u for u in units}
        assert by_key["Posting"].input_hash == _pack_for_service_unit(
            context=contexts[0], stories=stories, seam_waves=[],
            known_refs=known_refs, known_story_ids=known_story_ids).input_hash
        assert len(runner.calls) == 2

        cached_runner = _Runner()
        cached = asyncio.run(_generate_technical_design_with_ledger(
            runner=cached_runner, model="m", timeout_s=5, max_turns=4,
            contexts=contexts, stories=stories, seam_waves=[],
            known_refs=known_refs, known_story_ids=known_story_ids,
            ledger=repo, workspace_id=ws.id, repo_slug=ws.repo_slug,
            agent_run_id=run.id))
        assert cached.ok
        assert len(cached.payload["services"]) == 2
        assert cached_runner.calls == []


def test_technical_design_ledger_records_failed_service_unit():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)

    class _EmptyRunner(_Runner):
        async def run_structured(self, **kw):
            self.calls.append(kw)
            return {}

    with Session(eng) as s:
        repo = PgRepo(s)
        ws = repo.create_workspace(name="sample", repo_slug="repo", created_by="x")
        result = asyncio.run(_generate_technical_design_with_ledger(
            runner=_EmptyRunner(), model="m", timeout_s=5, max_turns=4,
            contexts=[{"name": "Posting", "member_programs": ["CBPOST1M"]}],
            stories=[], seam_waves=[], known_refs=["CBPOST1M"],
            known_story_ids=[], ledger=repo, workspace_id=ws.id,
            repo_slug=ws.repo_slug, agent_run_id=None))
        assert not result.ok
        units = repo.list_work_units(workspace_id=ws.id, stage="technical-design")
        assert len(units) == 1
        assert units[0].status == "failed"
        assert "no output" in units[0].error_cause
