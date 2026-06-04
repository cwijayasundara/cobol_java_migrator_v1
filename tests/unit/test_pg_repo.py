from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from cobol_modernizer.persistence.tables import Base
from cobol_modernizer.persistence.repo import PgRepo

def test_run_usage_rolls_into_run_and_workspace_budget():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        repo = PgRepo(s)
        ws = repo.create_workspace(name="sample", repo_slug="sample-cobol",
                                   created_by="cwijay@biz2bricks.ai")
        repo.set_budget(workspace_id=ws.id, scope="workspace", cap_usd=50.0)
        run = repo.start_run(workspace_id=ws.id, stage_id=None, role="brd",
                             model="claude-sonnet-4-6", started_by="cwijay@biz2bricks.ai")
        repo.set_budget(workspace_id=ws.id, scope="run", agent_run_id=run.id, cap_usd=5.0)
        repo.record_run_usage(workspace_id=ws.id, run_id=run.id,
                              token_usage={"input": 1000, "output": 500,
                                           "cache_read": 0, "cache_creation": 0},
                              cost_usd=1.25)
        s.commit()
        assert float(run.total_cost_usd) == 1.25
        assert run.input_tokens == 1000 and run.output_tokens == 500
        assert repo.budget_spent(workspace_id=ws.id, scope="workspace") == 1.25
        assert repo.budget_spent(workspace_id=ws.id, scope="run",
                                 agent_run_id=run.id) == 1.25


def test_repeated_usage_accumulates_not_overwrites():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        repo = PgRepo(s)
        ws = repo.create_workspace(name="sample", repo_slug="sample-cobol",
                                   created_by="cwijay@biz2bricks.ai")
        repo.set_budget(workspace_id=ws.id, scope="workspace", cap_usd=50.0)
        run = repo.start_run(workspace_id=ws.id, stage_id=None, role="brd",
                             model="claude-sonnet-4-6", started_by="cwijay@biz2bricks.ai")
        repo.set_budget(workspace_id=ws.id, scope="run", agent_run_id=run.id, cap_usd=5.0)
        repo.record_run_usage(workspace_id=ws.id, run_id=run.id,
                              token_usage={"input": 1000, "output": 500,
                                           "cache_read": 200, "cache_creation": 100},
                              cost_usd=1.25)
        repo.record_run_usage(workspace_id=ws.id, run_id=run.id,
                              token_usage={"input": 300, "output": 150,
                                           "cache_read": 50, "cache_creation": 25},
                              cost_usd=0.75)
        s.commit()
        assert run.input_tokens == 1300
        assert run.output_tokens == 650
        assert run.cache_read_tokens == 250
        assert run.cache_creation_tokens == 125
        assert float(run.total_cost_usd) == 2.0
        assert repo.budget_spent(workspace_id=ws.id, scope="workspace") == 2.0
        assert repo.budget_spent(workspace_id=ws.id, scope="run",
                                 agent_run_id=run.id) == 2.0


def test_work_unit_status_transitions_and_cache_lookup():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        repo = PgRepo(s)
        ws = repo.create_workspace(name="sample", repo_slug="carddemo",
                                   created_by="cwijay@biz2bricks.ai")
        run = repo.start_run(workspace_id=ws.id, stage_id=None, role="domain",
                             model="claude-sonnet-4-6", started_by="cwijay@biz2bricks.ai")
        unit = repo.create_work_unit(
            workspace_id=ws.id, repo_slug=ws.repo_slug, stage="domain-design",
            unit_type="aggregate", unit_key="AccountBalanceReporting",
            input_hash="hash-1", agent_run_id=run.id,
            parent_unit_ids=["parent-1"], model="claude-sonnet-4-6",
            timeout_s=120.0, max_turns=4)

        assert unit.status == "pending"
        assert unit.attempt == 0
        assert unit.parent_unit_ids == ["parent-1"]
        assert repo.find_cached_work_unit(
            workspace_id=ws.id, stage="domain-design", unit_type="aggregate",
            unit_key="AccountBalanceReporting", input_hash="hash-1") is None

        running = repo.mark_work_unit_running(unit.id, timeout_s=180.0, max_turns=6)
        assert running.status == "running"
        assert running.attempt == 1
        assert float(running.timeout_s) == 180.0
        assert running.max_turns == 6
        assert running.started_at is not None

        done = repo.mark_work_unit_succeeded(
            unit.id, payload={"aggregates": ["Account"]},
            token_usage={"input": 10, "output": 20}, cost_usd=0.5)
        assert done.status == "succeeded"
        assert done.payload["aggregates"] == ["Account"]
        assert done.token_usage["output"] == 20
        assert float(done.cost_usd) == 0.5
        assert done.finished_at is not None

        cached = repo.find_cached_work_unit(
            workspace_id=ws.id, stage="domain-design", unit_type="aggregate",
            unit_key="AccountBalanceReporting", input_hash="hash-1")
        assert cached is not None
        assert cached.id == unit.id


def test_failed_work_unit_is_not_cache_hit_and_can_be_deferred():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        repo = PgRepo(s)
        ws = repo.create_workspace(name="sample", repo_slug="carddemo",
                                   created_by="cwijay@biz2bricks.ai")
        unit = repo.create_work_unit(
            workspace_id=ws.id, repo_slug=ws.repo_slug, stage="technical-design",
            unit_type="service", unit_key="posting-service", input_hash="hash-2")

        failed = repo.mark_work_unit_failed(
            unit.id, error_cause="timeout after 120s",
            payload={"partial": True}, token_usage={"input": 100}, cost_usd=0.25)
        assert failed.status == "failed"
        assert failed.error_cause == "timeout after 120s"
        assert failed.payload["partial"] is True
        assert repo.find_cached_work_unit(
            workspace_id=ws.id, stage="technical-design", unit_type="service",
            unit_key="posting-service", input_hash="hash-2") is None

        deferred = repo.mark_work_unit_failed(
            unit.id, error_cause="attempt budget exhausted", deferred=True)
        assert deferred.status == "deferred"
        assert deferred.error_cause == "attempt budget exhausted"

        units = repo.list_work_units(workspace_id=ws.id, stage="technical-design")
        assert [u.id for u in units] == [unit.id]
