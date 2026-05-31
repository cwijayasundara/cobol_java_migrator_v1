from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from cobol_modernizer.persistence.tables import (
    Base, Workspace, AgentRun, AgentRunEvent,
)


def test_agent_run_event_roundtrip_and_ordering():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        ws = Workspace(name="CardDemo", repo_slug="aws-mf-carddemo",
                       created_by="cwijay@biz2bricks.ai")
        s.add(ws); s.flush()
        run = AgentRun(workspace_id=ws.id, stage_id=None, role="brd",
                       model="claude-sonnet-4-6", started_by="cwijay@biz2bricks.ai")
        s.add(run); s.flush()
        s.add(AgentRunEvent(run_id=run.id, seq=0, type="plan",
                            summary="drafting", detail={}))
        s.add(AgentRunEvent(run_id=run.id, seq=1, type="tool_call",
                            summary="neighbors(CBACT01C)", detail={"name": "CBACT01C"}))
        s.commit()
        rows = (s.query(AgentRunEvent)
                  .filter_by(run_id=run.id).order_by(AgentRunEvent.seq).all())
        assert [r.seq for r in rows] == [0, 1]
        assert rows[1].type == "tool_call"
        assert rows[1].detail["name"] == "CBACT01C"
