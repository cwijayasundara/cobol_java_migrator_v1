"""Run-event source for the cockpit SSE stream. emit_event appends an ordered
row to agent_run_event and publishes it to an in-process Broadcaster; the SSE
endpoint replays the table then streams live frames."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from cobol_modernizer.controlplane.deps import get_session
from cobol_modernizer.persistence.tables import AgentRun, AgentRunEvent


def _event_dict(ev: AgentRunEvent) -> dict[str, Any]:
    return {
        "type": ev.type, "run_id": ev.run_id, "seq": ev.seq,
        "ts": ev.ts.isoformat() if ev.ts is not None else None,
        "summary": ev.summary, "detail": ev.detail or {},
    }


def emit_event(session: Session, *, run_id: str, type: str, summary: str,
               detail: dict[str, Any] | None = None) -> dict[str, Any]:
    """Append the next event for a run (seq = max+1, starting at 0), persist it,
    publish to the broadcaster, and return the cockpit AgentEvent dict."""
    next_seq = session.execute(
        select(func.coalesce(func.max(AgentRunEvent.seq), -1) + 1)
        .where(AgentRunEvent.run_id == run_id)
    ).scalar_one()
    ev = AgentRunEvent(run_id=run_id, seq=int(next_seq), type=type,
                       summary=summary, detail=detail or {})
    session.add(ev)
    session.flush()
    payload = _event_dict(ev)
    BROADCASTER.publish_nowait(run_id, payload)
    return payload


class Broadcaster:
    """Process-local async pub/sub keyed by run_id."""

    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = {}

    def subscribe(self, run_id: str) -> tuple[asyncio.Queue, Callable[[], None]]:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(run_id, set()).add(q)

        def unsubscribe() -> None:
            self._subs.get(run_id, set()).discard(q)

        return q, unsubscribe

    async def publish(self, run_id: str, event: dict[str, Any]) -> None:
        for q in list(self._subs.get(run_id, set())):
            await q.put(event)

    def publish_nowait(self, run_id: str, event: dict[str, Any]) -> None:
        for q in list(self._subs.get(run_id, set())):
            q.put_nowait(event)


# module singleton shared by emit_event and the SSE endpoint
BROADCASTER = Broadcaster()


router = APIRouter(prefix="/api", tags=["controlplane-events"])

_TERMINAL = {"succeeded", "failed", "killed"}


@router.get("/workspaces/{wid}/runs/{run_id}/events")
async def run_events(wid: str, run_id: str, s: Session = Depends(get_session)):
    """SSE: replay persisted events for the run (seq order), then, if the run is
    still running, stream live events from the broadcaster until terminal/disconnect."""
    replay = s.execute(
        select(AgentRunEvent).where(AgentRunEvent.run_id == run_id)
        .order_by(AgentRunEvent.seq)
    ).scalars().all()
    run = s.get(AgentRun, run_id)
    is_terminal = run is not None and run.status in _TERMINAL

    q, unsubscribe = BROADCASTER.subscribe(run_id)

    async def gen():
        try:
            for ev in replay:
                yield {"data": json.dumps(_event_dict(ev))}
            if is_terminal:
                return
            while True:
                live = await q.get()
                yield {"data": json.dumps(live)}
                if live.get("type") in _TERMINAL:
                    return
        finally:
            unsubscribe()

    return EventSourceResponse(gen())
