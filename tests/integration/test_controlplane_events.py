import asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from cobol_modernizer.persistence.tables import Base, Workspace, AgentRun, AgentRunEvent
from cobol_modernizer.controlplane.events import emit_event, Broadcaster


def _seeded_session() -> tuple[Session, str]:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = Session(eng)
    ws = Workspace(name="CardDemo", repo_slug="aws-mf-carddemo", created_by="x")
    s.add(ws); s.flush()
    run = AgentRun(workspace_id=ws.id, stage_id=None, role="brd",
                   model="m", started_by="x")
    s.add(run); s.commit()
    return s, run.id


def test_emit_event_appends_ordered_rows_and_returns_dict():
    s, run_id = _seeded_session()
    e0 = emit_event(s, run_id=run_id, type="plan", summary="drafting")
    e1 = emit_event(s, run_id=run_id, type="tool_call", summary="neighbors(X)",
                    detail={"name": "X"})
    assert e0["seq"] == 0 and e1["seq"] == 1
    assert e1 == {"type": "tool_call", "run_id": run_id, "seq": 1,
                  "ts": e1["ts"], "summary": "neighbors(X)", "detail": {"name": "X"}}
    rows = s.query(AgentRunEvent).filter_by(run_id=run_id).order_by(AgentRunEvent.seq).all()
    assert [r.seq for r in rows] == [0, 1]


def test_broadcaster_fans_out_to_subscribers():
    async def run():
        b = Broadcaster()
        q, unsubscribe = b.subscribe("run-1")
        await b.publish("run-1", {"seq": 0, "summary": "hi"})
        got = await asyncio.wait_for(q.get(), timeout=1.0)
        unsubscribe()
        await b.publish("run-1", {"seq": 1, "summary": "after"})  # no subscriber now
        return got
    got = asyncio.run(run())
    assert got["summary"] == "hi"
