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


from datetime import datetime, timezone
from decimal import Decimal
from fastapi.testclient import TestClient


def _client_with_terminal_run():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    ts = datetime(2026, 5, 30, tzinfo=timezone.utc)
    with Session(eng) as s:
        ws = Workspace(id="ws-1", name="CardDemo", repo_slug="r", created_by="x")
        s.add(ws); s.flush()
        run = AgentRun(id="run-done", workspace_id="ws-1", stage_id=None, role="brd",
                       model="m", status="succeeded", started_by="x", started_at=ts,
                       finished_at=ts, input_tokens=0, output_tokens=0,
                       cache_read_tokens=0, cache_creation_tokens=0,
                       total_cost_usd=Decimal("0"))
        s.add(run); s.flush()
        emit_event(s, run_id="run-done", type="plan", summary="drafting")
        emit_event(s, run_id="run-done", type="result", summary="done")
        s.commit()
    from cobol_modernizer.api import app
    from cobol_modernizer.controlplane.deps import get_session

    def _override():
        ss = Session(eng)
        try:
            yield ss; ss.commit()
        finally:
            ss.close()
    app.dependency_overrides[get_session] = _override
    return TestClient(app), app, get_session


def test_sse_replays_persisted_events_then_closes_for_terminal_run():
    client, app, get_session = _client_with_terminal_run()
    try:
        resp = client.get("/api/workspaces/ws-1/runs/run-done/events")
        assert resp.status_code == 200
        body = resp.text
        assert "drafting" in body and "done" in body
        # match the qualified summary fragment so "done" can't collide with the
        # run id "run-done" that appears in every frame
        assert body.index('"summary": "drafting"') < body.index('"summary": "done"')
    finally:
        app.dependency_overrides.pop(get_session, None)
