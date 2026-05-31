from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from cobol_modernizer.persistence.tables import Base
from cobol_modernizer.persistence.repo import PgRepo

def test_run_usage_rolls_into_run_and_workspace_budget():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        repo = PgRepo(s)
        ws = repo.create_workspace(name="cardemo", repo_slug="aws-mf-carddemo",
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
