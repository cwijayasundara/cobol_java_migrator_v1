# Cockpit Control-Plane Endpoints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the UI Cockpit's ~14 control-plane endpoints (workspaces, stages, gates, artifacts, runs, budget, approval, graph, entity, SSE run-events) into the real FastAPI app, backed by the existing Postgres ORM models + read-only Neo4j layer + a new run-event source — JSON identical to the cockpit's MSW contract.

**Architecture:** A new focused package `src/cobol_modernizer/controlplane/` exposes one `APIRouter` that `api.py` includes. DB access via a `get_session` FastAPI dependency (sqlite override in tests); graph via a `get_neo4j` dependency (testcontainer override). SSE replays a new append-only `agent_run_event` table then live-streams via an in-process broadcaster.

**Tech Stack:** Python 3.12 + FastAPI + SQLAlchemy 2.0 + Pydantic 2 + sse-starlette; Neo4j read-only via the existing `Neo4jClient`/`queries.py`; pytest + sqlite (`StaticPool`) for unit, testcontainers Neo4j for integration.

**Spec:** `docs/superpowers/specs/2026-05-31-cockpit-control-plane-endpoints-design.md`

---

## File Structure

```
src/cobol_modernizer/
├── controlplane/                         # NEW package
│   ├── __init__.py                       # builds + exports controlplane_router
│   ├── deps.py                           # get_session, get_neo4j FastAPI deps
│   ├── serializers.py                    # ORM -> dict DTOs (match web/src/lib/types.ts)
│   ├── stages.py                         # canonical 11 stage_keys + gate map
│   ├── workspaces.py                     # workspace/stage/gate/artifact/run/budget + approval routes
│   ├── graph.py                          # /graph + /entity routes
│   └── events.py                         # AgentRunEvent emitter + Broadcaster + SSE endpoint
├── persistence/
│   ├── tables.py                         # MODIFY — add AgentRunEvent model
│   └── migrations/versions/0004_agent_run_event.py   # NEW
├── queries.py                            # MODIFY — add graph_overview + entity_detail reads
└── api.py                                # MODIFY — include controlplane_router

tests/
├── unit/
│   ├── test_controlplane_serializers.py  # DTO shape fidelity vs fixtures
│   ├── test_controlplane_stages.py       # canonical stage list
│   └── test_agent_run_event_table.py     # AgentRunEvent round-trip
└── integration/
    ├── conftest.py                       # NEW — cp_client fixture (sqlite + seed + overrides)
    ├── test_controlplane_workspaces_api.py   # DB-backed routes (sqlite)
    ├── test_controlplane_events.py           # emit_event + Broadcaster + SSE replay
    └── test_controlplane_graph_neo4j.py      # @pytest.mark.integration graph/entity
```

**Single responsibilities:**
- `deps.py` — the only place FastAPI obtains a DB session / Neo4j client.
- `serializers.py` — the only place ORM rows become cockpit JSON; no DB/HTTP.
- `stages.py` — the canonical 11-stage list + gate mapping (backend source of truth).
- `workspaces.py` — DB-backed CRUD + approval routes.
- `graph.py` — read-only graph HTTP wrappers.
- `events.py` — run-event persistence + broadcast + SSE.

---

## Task 1: AgentRunEvent table + migration 0004

**Files:**
- Modify: `src/cobol_modernizer/persistence/tables.py` (append model)
- Create: `src/cobol_modernizer/persistence/migrations/versions/0004_agent_run_event.py`
- Test: `tests/unit/test_agent_run_event_table.py`

- [ ] **Step 1: Write the failing test** `tests/unit/test_agent_run_event_table.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_agent_run_event_table.py -q`
Expected: FAIL — `ImportError: cannot import name 'AgentRunEvent'`.

- [ ] **Step 3: Append the model to `src/cobol_modernizer/persistence/tables.py`** (end of file; reuse existing `Base`, `_uuid`, `_now`, and the already-imported `String`, `Integer`, `JSON`, `DateTime`, `ForeignKey`, `UniqueConstraint`, `Mapped`, `mapped_column`):

```python
class AgentRunEvent(Base):
    """Append-only per-run event log feeding the cockpit SSE stream. One row per
    emitted event; (run_id, seq) is unique and monotonically increasing per run."""
    __tablename__ = "agent_run_event"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_run.id", ondelete="CASCADE"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    type: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_agent_run_event_seq"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_agent_run_event_table.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Create migration** `src/cobol_modernizer/persistence/migrations/versions/0004_agent_run_event.py`:

```python
"""agent_run_event: append-only per-run event log for the cockpit SSE stream

Revision ID: 0004_agent_run_event
Revises: 0003_deploy
Create Date: 2026-05-31 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_agent_run_event"
down_revision: Union[str, None] = "0003_deploy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_run_event",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_run.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "seq", name="uq_agent_run_event_seq"),
    )


def downgrade() -> None:
    op.drop_table("agent_run_event")
```

- [ ] **Step 6: Verify the migration parses + chains**

Run:
```bash
uv run python -c "
import importlib.util, pathlib
p = pathlib.Path('src/cobol_modernizer/persistence/migrations/versions/0004_agent_run_event.py')
spec = importlib.util.spec_from_file_location('m0004', p)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
assert m.revision == '0004_agent_run_event' and m.down_revision == '0003_deploy'
print('OK')
"
```
Expected: prints `OK`.

- [ ] **Step 7: Commit**

```bash
git add src/cobol_modernizer/persistence/tables.py src/cobol_modernizer/persistence/migrations/versions/0004_agent_run_event.py tests/unit/test_agent_run_event_table.py
git commit -m "feat(persistence): agent_run_event table + migration 0004 (SSE event log)"
```

---

## Task 2: Canonical stage list (`controlplane/stages.py`)

**Files:**
- Create: `src/cobol_modernizer/controlplane/__init__.py` (empty for now)
- Create: `src/cobol_modernizer/controlplane/stages.py`
- Test: `tests/unit/test_controlplane_stages.py`

- [ ] **Step 1: Write the failing test** `tests/unit/test_controlplane_stages.py`:

```python
from cobol_modernizer.controlplane.stages import JOURNEY_STAGES, gate_key_for


def test_eleven_canonical_stages_in_order():
    assert [s.key for s in JOURNEY_STAGES] == [
        "outcome", "intake", "parse", "graph", "explore",
        "blueprint", "seams", "plan", "design", "build", "verify",
    ]
    assert [s.ordinal for s in JOURNEY_STAGES] == list(range(11))


def test_gate_key_mapping():
    assert gate_key_for("blueprint") == "brd_groundedness"
    assert gate_key_for("build") == "code"
    assert gate_key_for("intake") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_controlplane_stages.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobol_modernizer.controlplane'`.

- [ ] **Step 3: Create `src/cobol_modernizer/controlplane/__init__.py`** (empty file for now — the router export is added in Task 8).

- [ ] **Step 4: Create `src/cobol_modernizer/controlplane/stages.py`:**

```python
"""The 11 canonical cockpit journey stages (backend source of truth, mirroring
web/src/lib/stages.ts) and their gate-key mapping."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StageDef:
    key: str
    label: str
    ordinal: int
    gate_key: str | None


JOURNEY_STAGES: list[StageDef] = [
    StageDef("outcome", "Outcome", 0, None),
    StageDef("intake", "Intake", 1, None),
    StageDef("parse", "Parse", 2, "parse"),
    StageDef("graph", "Graph", 3, "graph"),
    StageDef("explore", "Explore", 4, None),
    StageDef("blueprint", "Blueprint", 5, "brd_groundedness"),
    StageDef("seams", "Seams", 6, None),
    StageDef("plan", "Plan", 7, "stories_dag"),
    StageDef("design", "Design", 8, "design_data_ownership"),
    StageDef("build", "Build", 9, "code"),
    StageDef("verify", "Verify", 10, "equivalence"),
]


def gate_key_for(stage_key: str) -> str | None:
    for s in JOURNEY_STAGES:
        if s.key == stage_key:
            return s.gate_key
    return None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_controlplane_stages.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add src/cobol_modernizer/controlplane/__init__.py src/cobol_modernizer/controlplane/stages.py tests/unit/test_controlplane_stages.py
git commit -m "feat(controlplane): canonical 11 journey stages + gate mapping"
```

---

## Task 3: DTO serializers (`controlplane/serializers.py`)

**Files:**
- Create: `src/cobol_modernizer/controlplane/serializers.py`
- Test: `tests/unit/test_controlplane_serializers.py`

The DTOs must match `web/src/lib/types.ts` exactly so the backend is a drop-in for the cockpit MSW mocks. `Numeric` → `float`, `DateTime` → ISO string, `JSON` passthrough, `BigInteger` → `int`.

- [ ] **Step 1: Write the failing test** `tests/unit/test_controlplane_serializers.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal
from cobol_modernizer.persistence.tables import (
    Workspace, JourneyStage, AgentRun, Artifact, Gate, Approval, Budget,
)
from cobol_modernizer.controlplane.serializers import (
    workspace_dto, stage_dto, run_dto, artifact_dto, gate_dto, approval_dto, budget_dto,
)

TS = datetime(2026, 5, 30, tzinfo=timezone.utc)


def test_workspace_dto_shape():
    ws = Workspace(id="ws-1", name="CardDemo", repo_slug="aws-mf-carddemo",
                   graph_snapshot="snap-001", created_by="cwijay@biz2bricks.ai",
                   created_at=TS, status="active")
    d = workspace_dto(ws)
    assert d == {
        "id": "ws-1", "name": "CardDemo", "repo_slug": "aws-mf-carddemo",
        "graph_snapshot": "snap-001", "created_by": "cwijay@biz2bricks.ai",
        "created_at": "2026-05-30T00:00:00+00:00", "status": "active",
    }


def test_budget_dto_numeric_to_float():
    b = Budget(id="bud-1", workspace_id="ws-1", scope="workspace", agent_run_id=None,
               cap_usd=Decimal("50"), spent_usd=Decimal("18.42"), killed=False,
               updated_at=TS)
    d = budget_dto(b)
    assert d["cap_usd"] == 50.0 and d["spent_usd"] == 18.42 and d["killed"] is False
    assert isinstance(d["cap_usd"], float)


def test_run_dto_tokens_and_cost():
    r = AgentRun(id="run-1", workspace_id="ws-1", stage_id="stg-blueprint", role="brd",
                 model="claude-sonnet-4-6", status="running", started_by="x",
                 started_at=TS, finished_at=None, input_tokens=12000, output_tokens=3400,
                 cache_read_tokens=8000, cache_creation_tokens=2000,
                 total_cost_usd=Decimal("0.42"), error=None)
    d = run_dto(r)
    assert d["input_tokens"] == 12000 and d["total_cost_usd"] == 0.42
    assert d["finished_at"] is None and d["status"] == "running"


def test_artifact_gate_approval_stage_dtos():
    art = Artifact(id="art-1", workspace_id="ws-1", stage_id="stg-blueprint",
                   agent_run_id="run-1", kind="brd", version=1,
                   object_uri="minio://a", content_hash="sha256:abc",
                   evidence_map={"REQ-001": ["CBACT01C"]}, created_at=TS)
    assert artifact_dto(art)["evidence_map"] == {"REQ-001": ["CBACT01C"]}
    g = Gate(id="gate-brd", workspace_id="ws-1", stage_id="stg-blueprint",
             gate_key="brd_groundedness", status="open",
             threshold={"min_weighted": 4.2}, result={"weighted": 4.35}, updated_at=TS)
    assert gate_dto(g)["gate_key"] == "brd_groundedness" and gate_dto(g)["status"] == "open"
    ap = Approval(id="ap-1", gate_id="gate-brd", decision="approved",
                  approver_email="lead@biz2bricks.ai", approver_role="lead_engineer",
                  risk_accepted=False, rationale="ok", decided_at=TS)
    assert approval_dto(ap)["approver_email"] == "lead@biz2bricks.ai"
    st = JourneyStage(id="stg-blueprint", workspace_id="ws-1", stage_key="blueprint",
                      ordinal=5, status="running", updated_at=TS)
    assert stage_dto(st) == {"id": "stg-blueprint", "workspace_id": "ws-1",
                             "stage_key": "blueprint", "ordinal": 5,
                             "status": "running", "updated_at": "2026-05-30T00:00:00+00:00"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_controlplane_serializers.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobol_modernizer.controlplane.serializers'`.

- [ ] **Step 3: Create `src/cobol_modernizer/controlplane/serializers.py`:**

```python
"""Pure ORM-instance -> dict serializers producing JSON identical to the cockpit
DTOs in web/src/lib/types.ts. No DB or HTTP here. Numeric->float, datetime->ISO,
JSON columns passthrough."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from cobol_modernizer.persistence.tables import (
    AgentRun, Approval, Artifact, Budget, Gate, JourneyStage, Workspace,
)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _f(v: Decimal | float | int | None) -> float | None:
    return float(v) if v is not None else None


def workspace_dto(ws: Workspace) -> dict[str, Any]:
    return {
        "id": ws.id, "name": ws.name, "repo_slug": ws.repo_slug,
        "graph_snapshot": ws.graph_snapshot, "created_by": ws.created_by,
        "created_at": _iso(ws.created_at), "status": ws.status,
    }


def stage_dto(s: JourneyStage) -> dict[str, Any]:
    return {
        "id": s.id, "workspace_id": s.workspace_id, "stage_key": s.stage_key,
        "ordinal": s.ordinal, "status": s.status, "updated_at": _iso(s.updated_at),
    }


def run_dto(r: AgentRun) -> dict[str, Any]:
    return {
        "id": r.id, "workspace_id": r.workspace_id, "stage_id": r.stage_id,
        "role": r.role, "model": r.model, "status": r.status,
        "started_by": r.started_by, "started_at": _iso(r.started_at),
        "finished_at": _iso(r.finished_at), "input_tokens": r.input_tokens,
        "output_tokens": r.output_tokens, "cache_read_tokens": r.cache_read_tokens,
        "cache_creation_tokens": r.cache_creation_tokens,
        "total_cost_usd": _f(r.total_cost_usd), "error": r.error,
    }


def artifact_dto(a: Artifact) -> dict[str, Any]:
    return {
        "id": a.id, "workspace_id": a.workspace_id, "stage_id": a.stage_id,
        "agent_run_id": a.agent_run_id, "kind": a.kind, "version": a.version,
        "object_uri": a.object_uri, "content_hash": a.content_hash,
        "evidence_map": a.evidence_map or {}, "created_at": _iso(a.created_at),
    }


def gate_dto(g: Gate) -> dict[str, Any]:
    return {
        "id": g.id, "workspace_id": g.workspace_id, "stage_id": g.stage_id,
        "gate_key": g.gate_key, "status": g.status, "threshold": g.threshold or {},
        "result": g.result or {}, "updated_at": _iso(g.updated_at),
    }


def approval_dto(ap: Approval) -> dict[str, Any]:
    return {
        "id": ap.id, "gate_id": ap.gate_id, "decision": ap.decision,
        "approver_email": ap.approver_email, "approver_role": ap.approver_role,
        "risk_accepted": ap.risk_accepted, "rationale": ap.rationale,
        "decided_at": _iso(ap.decided_at),
    }


def budget_dto(b: Budget) -> dict[str, Any]:
    return {
        "id": b.id, "workspace_id": b.workspace_id, "scope": b.scope,
        "agent_run_id": b.agent_run_id, "cap_usd": _f(b.cap_usd),
        "spent_usd": _f(b.spent_usd), "killed": b.killed, "updated_at": _iso(b.updated_at),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_controlplane_serializers.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/controlplane/serializers.py tests/unit/test_controlplane_serializers.py
git commit -m "feat(controlplane): ORM->DTO serializers matching cockpit types.ts"
```

---

## Task 4: DB session dependency (`controlplane/deps.py`)

**Files:**
- Create: `src/cobol_modernizer/controlplane/deps.py`
- (No standalone test — exercised by Task 6+ via `dependency_overrides`.)

- [ ] **Step 1: Create `src/cobol_modernizer/controlplane/deps.py`:**

```python
"""FastAPI dependencies for the control plane: a Postgres Session and a read-only
Neo4j client. Both are overridden in tests via app.dependency_overrides (sqlite
session; testcontainer Neo4j)."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Iterator

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from cobol_modernizer.persistence.db import make_engine


@lru_cache(maxsize=1)
def _engine() -> Engine:
    return make_engine(os.environ["POSTGRES_URL"])


def get_session() -> Iterator[Session]:
    """Yield a transactional Session: commit on success, rollback on error."""
    session = Session(_engine())
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_neo4j() -> Iterator[object]:
    """Yield a read-only Neo4jClient built from env. Overridden in tests."""
    from cobol_modernizer.neo4j_client import Neo4jClient

    client = Neo4jClient(
        uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        user=os.environ.get("NEO4J_USER", "neo4j"),
        password=os.environ.get("NEO4J_PASSWORD", "neo4j"),
    )
    try:
        yield client
    finally:
        client.close()
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `uv run python -c "from cobol_modernizer.controlplane.deps import get_session, get_neo4j; print('OK')"`
Expected: prints `OK`.

- [ ] **Step 3: Commit**

```bash
git add src/cobol_modernizer/controlplane/deps.py
git commit -m "feat(controlplane): get_session + get_neo4j FastAPI dependencies"
```

> **Note on `Neo4jClient` constructor:** the test in Step 2 only imports `deps`; it does not instantiate the client. If `from cobol_modernizer.neo4j_client import Neo4jClient` fails or the constructor kwargs differ, fix the import/kwargs to match the real class (verified signature: `Neo4jClient(uri=, user=, password=)`) before committing.

---

## Task 5: Run-event emitter + Broadcaster (`controlplane/events.py`, no SSE route yet)

**Files:**
- Create: `src/cobol_modernizer/controlplane/events.py`
- Test: `tests/integration/test_controlplane_events.py`

- [ ] **Step 1: Write the failing test** `tests/integration/test_controlplane_events.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_controlplane_events.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobol_modernizer.controlplane.events'`.

- [ ] **Step 3: Create `src/cobol_modernizer/controlplane/events.py`** (emitter + broadcaster only; SSE route added in Task 7):

```python
"""Run-event source for the cockpit SSE stream. emit_event appends an ordered
row to agent_run_event and publishes it to an in-process Broadcaster; the SSE
endpoint (events route, added later) replays the table then streams live frames."""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cobol_modernizer.persistence.tables import AgentRunEvent


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_controlplane_events.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/cobol_modernizer/controlplane/events.py tests/integration/test_controlplane_events.py
git commit -m "feat(controlplane): run-event emitter + in-process broadcaster"
```

---

## Task 6: DB-backed workspace routes + approval (`controlplane/workspaces.py`)

**Files:**
- Create: `src/cobol_modernizer/controlplane/workspaces.py`
- Create: `tests/integration/conftest.py` (the `cp_client` fixture)
- Test: `tests/integration/test_controlplane_workspaces_api.py`

- [ ] **Step 1: Create the test fixture** `tests/integration/conftest.py`:

```python
import pytest
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from cobol_modernizer.persistence.tables import (
    Base, Workspace, JourneyStage, Gate, Budget, AgentRun, Artifact,
)
from cobol_modernizer.controlplane.deps import get_session

TS = datetime(2026, 5, 30, tzinfo=timezone.utc)


@pytest.fixture
def cp_client():
    """A TestClient with get_session overridden by a seeded in-memory sqlite DB.
    Seeds the canonical workspace mirroring web/src/test/fixtures/controlplane.ts."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as seed:
        seed.add(Workspace(id="ws-1", name="CardDemo", repo_slug="aws-mf-carddemo",
                           graph_snapshot="snap-001", created_by="cwijay@biz2bricks.ai",
                           created_at=TS, status="active"))
        keys = ["outcome","intake","parse","graph","explore","blueprint",
                "seams","plan","design","build","verify"]
        for i, k in enumerate(keys):
            seed.add(JourneyStage(id=f"stg-{k}", workspace_id="ws-1", stage_key=k,
                                  ordinal=i,
                                  status="passed" if i < 5 else "running" if i == 5 else "pending",
                                  updated_at=TS))
        seed.add(Gate(id="gate-brd", workspace_id="ws-1", stage_id="stg-blueprint",
                      gate_key="brd_groundedness", status="open",
                      threshold={"min_weighted": 4.2}, result={"weighted": 4.35},
                      updated_at=TS))
        seed.add(Budget(id="bud-1", workspace_id="ws-1", scope="workspace",
                        agent_run_id=None, cap_usd=Decimal("50"),
                        spent_usd=Decimal("18.42"), killed=False, updated_at=TS))
        seed.add(AgentRun(id="run-1", workspace_id="ws-1", stage_id="stg-blueprint",
                          role="brd", model="claude-sonnet-4-6", status="running",
                          started_by="cwijay@biz2bricks.ai", started_at=TS,
                          input_tokens=12000, output_tokens=3400,
                          cache_read_tokens=8000, cache_creation_tokens=2000,
                          total_cost_usd=Decimal("0.42")))
        seed.add(Artifact(id="art-brd-1", workspace_id="ws-1", stage_id="stg-blueprint",
                          agent_run_id="run-1", kind="brd", version=1,
                          object_uri="minio://artifacts/ws-1/brd/v1.html",
                          content_hash="sha256:abc",
                          evidence_map={"REQ-001": ["CBACT01C", "CBACT01C.1000-MAIN"]},
                          created_at=TS))
        seed.commit()

    from cobol_modernizer.api import app

    def _override() -> object:
        s = Session(engine)
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    app.dependency_overrides[get_session] = _override
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_session, None)
```

- [ ] **Step 2: Write the failing test** `tests/integration/test_controlplane_workspaces_api.py`:

```python
def test_list_and_get_workspaces(cp_client):
    rows = cp_client.get("/api/workspaces").json()
    assert len(rows) == 1 and rows[0]["repo_slug"] == "aws-mf-carddemo"
    one = cp_client.get("/api/workspaces/ws-1").json()
    assert one["created_by"] == "cwijay@biz2bricks.ai"
    assert cp_client.get("/api/workspaces/nope").status_code == 404


def test_stages_gates_artifacts_runs_budget(cp_client):
    stages = cp_client.get("/api/workspaces/ws-1/stages").json()
    assert [s["stage_key"] for s in stages][:2] == ["outcome", "intake"]
    assert len(stages) == 11
    gates = cp_client.get("/api/workspaces/ws-1/gates").json()
    assert gates[0]["gate_key"] == "brd_groundedness"
    arts = cp_client.get("/api/workspaces/ws-1/artifacts").json()
    assert arts[0]["kind"] == "brd"
    assert cp_client.get("/api/workspaces/ws-1/artifacts/art-brd-1").json()["version"] == 1
    runs = cp_client.get("/api/workspaces/ws-1/runs").json()
    assert runs[0]["id"] == "run-1" and runs[0]["total_cost_usd"] == 0.42
    budget = cp_client.get("/api/workspaces/ws-1/budget").json()
    assert budget["cap_usd"] == 50.0 and budget["spent_usd"] == 18.42


def test_create_workspace_seeds_stages_and_budget(cp_client):
    created = cp_client.post("/api/workspaces", json={
        "name": "Loans", "repo_slug": "aws-mf-loans", "created_by": "lead@biz2bricks.ai",
    }).json()
    wid = created["id"]
    assert created["name"] == "Loans" and created["status"] == "active"
    stages = cp_client.get(f"/api/workspaces/{wid}/stages").json()
    assert len(stages) == 11 and stages[0]["status"] == "running"
    budget = cp_client.get(f"/api/workspaces/{wid}/budget").json()
    assert budget["cap_usd"] == 50.0 and budget["spent_usd"] == 0.0


def test_start_run_creates_running_run(cp_client):
    run = cp_client.post("/api/workspaces/ws-1/runs", json={
        "stage_key": "blueprint", "role": "brd", "started_by": "lead@biz2bricks.ai",
    }).json()
    assert run["status"] == "running" and run["role"] == "brd"
    assert run["stage_id"] == "stg-blueprint" and run["model"]


def test_approval_transitions_gate(cp_client):
    res = cp_client.post("/api/gates/gate-brd/approval", json={
        "decision": "approved", "approver_email": "lead@biz2bricks.ai",
        "approver_role": "lead_engineer", "risk_accepted": False,
        "rationale": "groundedness cleared",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["decision"] == "approved" and body["approver_email"] == "lead@biz2bricks.ai"
    gates = cp_client.get("/api/workspaces/ws-1/gates").json()
    assert next(g for g in gates if g["id"] == "gate-brd")["status"] == "passed"


def test_waive_requires_risk_accepted(cp_client):
    res = cp_client.post("/api/gates/gate-brd/approval", json={
        "decision": "waived_with_risk", "approver_email": "lead@biz2bricks.ai",
        "approver_role": "risk_officer", "risk_accepted": False, "rationale": "no",
    })
    assert res.status_code == 400


def test_approval_unknown_gate_404(cp_client):
    res = cp_client.post("/api/gates/nope/approval", json={
        "decision": "approved", "approver_email": "x@y.z",
        "approver_role": "lead_engineer", "risk_accepted": False, "rationale": "ok",
    })
    assert res.status_code == 404
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_controlplane_workspaces_api.py -q`
Expected: FAIL — 404s on every route (the router isn't wired yet) / `ModuleNotFoundError` for `workspaces`.

- [ ] **Step 4: Create `src/cobol_modernizer/controlplane/workspaces.py`:**

```python
"""DB-backed cockpit control-plane routes: workspaces, stages, gates, artifacts,
runs, budget, and the attributed gate-approval transition."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from cobol_modernizer.controlplane.deps import get_session
from cobol_modernizer.controlplane.serializers import (
    approval_dto, artifact_dto, budget_dto, gate_dto, run_dto, stage_dto, workspace_dto,
)
from cobol_modernizer.controlplane.stages import JOURNEY_STAGES
from cobol_modernizer.cost.tiering import resolve_model
from cobol_modernizer.persistence.tables import (
    AgentRun, Approval, Artifact, Budget, Gate, JourneyStage, Workspace,
)

router = APIRouter(prefix="/api", tags=["controlplane"])

_DECISION_TO_GATE = {
    "approved": "passed", "rejected": "failed", "waived_with_risk": "waived",
}


class CreateWorkspaceBody(BaseModel):
    name: str
    repo_slug: str
    created_by: str


class StartRunBody(BaseModel):
    stage_key: str
    role: str
    started_by: str


class ApprovalBody(BaseModel):
    decision: str
    approver_email: str
    approver_role: str
    risk_accepted: bool = False
    rationale: str


def _get_ws(s: Session, wid: str) -> Workspace:
    ws = s.get(Workspace, wid)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"workspace {wid} not found")
    return ws


@router.get("/workspaces")
def list_workspaces(s: Session = Depends(get_session)) -> list[dict]:
    rows = s.execute(select(Workspace).order_by(Workspace.created_at)).scalars().all()
    return [workspace_dto(w) for w in rows]


@router.get("/workspaces/{wid}")
def get_workspace(wid: str, s: Session = Depends(get_session)) -> dict:
    return workspace_dto(_get_ws(s, wid))


@router.post("/workspaces")
def create_workspace(body: CreateWorkspaceBody, s: Session = Depends(get_session)) -> dict:
    ws = Workspace(name=body.name, repo_slug=body.repo_slug, created_by=body.created_by)
    s.add(ws); s.flush()
    for st in JOURNEY_STAGES:
        s.add(JourneyStage(workspace_id=ws.id, stage_key=st.key, ordinal=st.ordinal,
                           status="running" if st.ordinal == 0 else "pending"))
    s.add(Budget(workspace_id=ws.id, scope="workspace", agent_run_id=None,
                 cap_usd=50, spent_usd=0, killed=False))
    s.flush()
    return workspace_dto(ws)


@router.get("/workspaces/{wid}/stages")
def list_stages(wid: str, s: Session = Depends(get_session)) -> list[dict]:
    _get_ws(s, wid)
    rows = s.execute(select(JourneyStage).where(JourneyStage.workspace_id == wid)
                     .order_by(JourneyStage.ordinal)).scalars().all()
    return [stage_dto(x) for x in rows]


@router.get("/workspaces/{wid}/gates")
def list_gates(wid: str, s: Session = Depends(get_session)) -> list[dict]:
    _get_ws(s, wid)
    rows = s.execute(select(Gate).where(Gate.workspace_id == wid)).scalars().all()
    return [gate_dto(x) for x in rows]


@router.get("/workspaces/{wid}/artifacts")
def list_artifacts(wid: str, s: Session = Depends(get_session)) -> list[dict]:
    _get_ws(s, wid)
    rows = s.execute(select(Artifact).where(Artifact.workspace_id == wid)
                     .order_by(Artifact.created_at.desc())).scalars().all()
    return [artifact_dto(x) for x in rows]


@router.get("/workspaces/{wid}/artifacts/{aid}")
def get_artifact(wid: str, aid: str, s: Session = Depends(get_session)) -> dict:
    art = s.get(Artifact, aid)
    if art is None or art.workspace_id != wid:
        raise HTTPException(status_code=404, detail=f"artifact {aid} not found")
    return artifact_dto(art)


@router.get("/workspaces/{wid}/runs")
def list_runs(wid: str, s: Session = Depends(get_session)) -> list[dict]:
    _get_ws(s, wid)
    rows = s.execute(select(AgentRun).where(AgentRun.workspace_id == wid)
                     .order_by(AgentRun.started_at.desc())).scalars().all()
    return [run_dto(x) for x in rows]


@router.post("/workspaces/{wid}/runs")
def start_run(wid: str, body: StartRunBody, s: Session = Depends(get_session)) -> dict:
    _get_ws(s, wid)
    stage = s.execute(select(JourneyStage).where(
        JourneyStage.workspace_id == wid,
        JourneyStage.stage_key == body.stage_key)).scalars().first()
    run = AgentRun(workspace_id=wid, stage_id=stage.id if stage else None,
                   role=body.role, model=resolve_model(body.role), status="running",
                   started_by=body.started_by, input_tokens=0, output_tokens=0,
                   cache_read_tokens=0, cache_creation_tokens=0, total_cost_usd=0)
    s.add(run); s.flush()
    return run_dto(run)


@router.get("/workspaces/{wid}/budget")
def get_budget(wid: str, s: Session = Depends(get_session)) -> dict:
    _get_ws(s, wid)
    b = s.execute(select(Budget).where(Budget.workspace_id == wid,
                                        Budget.scope == "workspace")).scalars().first()
    if b is None:
        raise HTTPException(status_code=404, detail="no workspace budget")
    return budget_dto(b)


@router.post("/gates/{gate_id}/approval")
def submit_approval(gate_id: str, body: ApprovalBody,
                    s: Session = Depends(get_session)) -> dict:
    gate = s.get(Gate, gate_id)
    if gate is None:
        raise HTTPException(status_code=404, detail=f"gate {gate_id} not found")
    if body.decision not in _DECISION_TO_GATE:
        raise HTTPException(status_code=400, detail=f"bad decision {body.decision}")
    if body.decision == "waived_with_risk" and not body.risk_accepted:
        raise HTTPException(status_code=400, detail="waive requires risk_accepted")
    ap = Approval(gate_id=gate_id, decision=body.decision,
                  approver_email=body.approver_email, approver_role=body.approver_role,
                  risk_accepted=body.risk_accepted, rationale=body.rationale,
                  decided_at=datetime.now(timezone.utc))
    s.add(ap)
    gate.status = _DECISION_TO_GATE[body.decision]
    s.flush()
    return approval_dto(ap)
```

- [ ] **Step 5: Temporarily wire the router so the test can run.** Append to `src/cobol_modernizer/api.py` (this import+include is finalized in Task 8; add it now so Task 6 tests pass):

```python
from cobol_modernizer.controlplane.workspaces import router as _cp_workspaces_router
app.include_router(_cp_workspaces_router)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_controlplane_workspaces_api.py -q`
Expected: PASS (7 passed).

- [ ] **Step 7: Commit**

```bash
git add src/cobol_modernizer/controlplane/workspaces.py tests/integration/conftest.py tests/integration/test_controlplane_workspaces_api.py src/cobol_modernizer/api.py
git commit -m "feat(controlplane): DB-backed workspace/stage/gate/artifact/run/budget + approval routes"
```

---

## Task 7: SSE run-events route (`controlplane/events.py` — add the endpoint + router)

**Files:**
- Modify: `src/cobol_modernizer/controlplane/events.py` (add router + SSE endpoint)
- Modify: `pyproject.toml` (declare `sse-starlette`)
- Test: append to `tests/integration/test_controlplane_events.py`

- [ ] **Step 1: Declare the dependency.** In `pyproject.toml`, add to the `dependencies` list (after `"uvicorn>=0.32",`):

```toml
  "sse-starlette>=2.1",
```

Then run: `uv sync` (Expected: resolves, `sse-starlette` installed.)

- [ ] **Step 2: Write the failing test** — append to `tests/integration/test_controlplane_events.py`:

```python
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
        # both persisted events are present, in order
        assert body.index("drafting") < body.index("done")
    finally:
        app.dependency_overrides.pop(get_session, None)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_controlplane_events.py -q`
Expected: FAIL — 404 (no events route yet) / `AttributeError` (`router` not defined).

- [ ] **Step 4: Add the SSE endpoint + router to `src/cobol_modernizer/controlplane/events.py`** (append these imports at the top and the route at the bottom):

Add to the imports block at the top of the file:

```python
from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse
import json

from cobol_modernizer.controlplane.deps import get_session
from cobol_modernizer.persistence.tables import AgentRun
```

Append at the end of the file:

```python
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
```

- [ ] **Step 5: Temporarily include the events router** so its SSE test resolves against `app`. Append to `src/cobol_modernizer/api.py` (consolidated into the single `controlplane_router` include in Task 9):

```python
from cobol_modernizer.controlplane.events import router as _cp_events_router
app.include_router(_cp_events_router)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_controlplane_events.py -q`
Expected: PASS (3 passed).

- [ ] **Step 7: Commit**

```bash
git add src/cobol_modernizer/controlplane/events.py pyproject.toml tests/integration/test_controlplane_events.py src/cobol_modernizer/api.py
git commit -m "feat(controlplane): SSE run-events endpoint (replay persisted + live broadcast)"
```

---

## Task 8: Read-only graph queries + `/graph` and `/entity` routes (`controlplane/graph.py`)

**Files:**
- Modify: `src/cobol_modernizer/queries.py` (add `graph_overview` + `entity_detail`)
- Create: `src/cobol_modernizer/controlplane/graph.py`
- Modify: `src/cobol_modernizer/api.py` (temp-include the graph router)
- Test: `tests/integration/test_controlplane_graph_neo4j.py`

> Graph is built BEFORE the final router assembly (Task 9) because `controlplane/__init__.py` imports `graph.py`.

- [ ] **Step 1: Add two read-only methods to `CodeGraphQueries` in `src/cobol_modernizer/queries.py`** (match the existing class's `self._client.run(...)` pattern — verify the client attribute name in the file; the read returns `list[dict]`):

```python
def graph_overview(self, repo: str | None = None, limit: int = 300) -> dict:
    """Read-only: nodes (capped at limit) + the relationships among them, shaped
    for the cockpit GraphView (nodes:{id,name,kind,file,summary}, links:{source,target,type})."""
    node_rows = self._client.run(
        """
        MATCH (n:Entity)
        WHERE $repo IS NULL OR n.repo = $repo
        RETURN n.qualified_name AS id, n.simple_name AS name, n.kind AS kind,
               n.file_path AS file, n.semantic_summary AS summary
        LIMIT $limit
        """,
        repo=repo, limit=limit,
    )
    ids = [r["id"] for r in node_rows]
    link_rows = self._client.run(
        """
        MATCH (a:Entity)-[r]->(b:Entity)
        WHERE a.qualified_name IN $ids AND b.qualified_name IN $ids
        RETURN a.qualified_name AS source, b.qualified_name AS target, type(r) AS type
        """,
        ids=ids,
    )
    return {"nodes": node_rows, "links": link_rows}


def entity_detail(self, qualified_name: str) -> dict | None:
    """Read-only: an entity's props + incoming/outgoing relationships, shaped for
    the cockpit EntityDetail. Returns None if the entity is unknown."""
    ent = self._client.run(
        "MATCH (n:Entity {qualified_name: $q}) RETURN properties(n) AS props",
        q=qualified_name,
    )
    if not ent:
        return None
    incoming = self._client.run(
        """
        MATCH (s:Entity)-[r]->(n:Entity {qualified_name: $q})
        RETURN s.qualified_name AS source, s.kind AS source_kind, type(r) AS relationship
        """, q=qualified_name,
    )
    outgoing = self._client.run(
        """
        MATCH (n:Entity {qualified_name: $q})-[r]->(t:Entity)
        RETURN t.qualified_name AS target, t.kind AS target_kind, type(r) AS relationship
        """, q=qualified_name,
    )
    return {"entity": ent[0]["props"], "incoming": incoming, "outgoing": outgoing}
```

> **Note:** verify the node label (`Entity`) and property names (`qualified_name`, `simple_name`, `kind`, `file_path`, `semantic_summary`, `repo`) against the actual schema in `neo4j_client.py`/`queries.py`. If they differ, adjust the Cypher to the real names before running. These are READ-only `MATCH ... RETURN` queries (no writes).

- [ ] **Step 2: Create `src/cobol_modernizer/controlplane/graph.py`:**

```python
"""Read-only graph HTTP wrappers for the cockpit GraphView + entity drawer.
Calls CodeGraphQueries read methods; never writes to Neo4j."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from cobol_modernizer.controlplane.deps import get_neo4j
from cobol_modernizer.queries import CodeGraphQueries

router = APIRouter(prefix="/api", tags=["controlplane-graph"])


@router.get("/graph")
def get_graph(repo: str | None = None, limit: int = 300,
              client=Depends(get_neo4j)) -> dict:
    return CodeGraphQueries(client).graph_overview(repo=repo, limit=limit)


@router.get("/entity/{qname}")
def get_entity(qname: str, client=Depends(get_neo4j)) -> dict:
    detail = CodeGraphQueries(client).entity_detail(qname)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"entity {qname} not found")
    return detail
```

> **Note:** verify `CodeGraphQueries.__init__` takes the client positionally (it wraps a `Neo4jClient`). If its constructor differs, adjust the call. Check `queries.py` `class CodeGraphQueries` signature.

- [ ] **Step 3: Temporarily include the graph router** so its integration test resolves against `app`. Append to `src/cobol_modernizer/api.py` (consolidated into the single `controlplane_router` include in Task 9):

```python
from cobol_modernizer.controlplane.graph import router as _cp_graph_router
app.include_router(_cp_graph_router)
```

- [ ] **Step 4: Write the integration test** `tests/integration/test_controlplane_graph_neo4j.py`:

```python
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_graph_and_entity_endpoints(neo4j_graph):
    # seed a tiny subgraph (two programs, one CALLS edge)
    neo4j_graph.merge_entity("CBACT01C", "Program",
                             {"simple_name": "CBACT01C", "kind": "Program",
                              "file_path": "CBACT01C.cbl", "semantic_summary": "reader"},
                             repo="aws-mf-carddemo")
    neo4j_graph.merge_entity("CBACT01C.1000-MAIN", "Paragraph",
                             {"simple_name": "1000-MAIN", "kind": "Paragraph",
                              "file_path": "CBACT01C.cbl", "semantic_summary": None},
                             repo="aws-mf-carddemo")
    neo4j_graph.merge_relationship("CBACT01C", "CBACT01C.1000-MAIN", "CONTAINS",
                                   {}, allow_unresolved=False, repo="aws-mf-carddemo")

    from cobol_modernizer.api import app
    from cobol_modernizer.controlplane.deps import get_neo4j
    app.dependency_overrides[get_neo4j] = lambda: neo4j_graph
    try:
        client = TestClient(app)
        g = client.get("/api/graph?repo=aws-mf-carddemo&limit=50").json()
        ids = {n["id"] for n in g["nodes"]}
        assert "CBACT01C" in ids and "CBACT01C.1000-MAIN" in ids
        assert any(l["type"] == "CONTAINS" for l in g["links"])
        e = client.get("/api/entity/CBACT01C").json()
        assert e["entity"]["qualified_name"] == "CBACT01C"
        assert any(o["relationship"] == "CONTAINS" for o in e["outgoing"])
        assert client.get("/api/entity/NOSUCH").status_code == 404
    finally:
        app.dependency_overrides.pop(get_neo4j, None)
```

- [ ] **Step 5: Run the test**

Run: `uv run pytest tests/integration/test_controlplane_graph_neo4j.py -q`
Expected: PASS (1 passed) if Docker+Neo4j available; otherwise SKIPPED. If it runs and the Cypher/property names mismatch the real schema, fix them (Step 1/2 notes) until green.

- [ ] **Step 6: Commit**

```bash
git add src/cobol_modernizer/queries.py src/cobol_modernizer/controlplane/graph.py tests/integration/test_controlplane_graph_neo4j.py src/cobol_modernizer/api.py
git commit -m "feat(controlplane): read-only /graph + /entity endpoints over Neo4j"
```

---

## Task 9: Assemble `controlplane_router` + finalize `api.py` wiring

By now `api.py` has THREE temporary includes (workspaces from Task 6, events from Task 7, graph from Task 8). This task consolidates them into one `controlplane_router` included with a single line, and all three sub-routers (`workspaces.py`, `events.py`, `graph.py`) now exist so the package import resolves.

**Files:**
- Modify: `src/cobol_modernizer/controlplane/__init__.py`
- Modify: `src/cobol_modernizer/api.py`
- Test: `tests/integration/test_controlplane_router_wiring.py`

- [ ] **Step 1: Write the failing test** `tests/integration/test_controlplane_router_wiring.py`:

```python
from cobol_modernizer.controlplane import controlplane_router


def test_router_exposes_all_cockpit_paths():
    paths = {r.path for r in controlplane_router.routes}
    expected = {
        "/api/workspaces", "/api/workspaces/{wid}",
        "/api/workspaces/{wid}/stages", "/api/workspaces/{wid}/gates",
        "/api/workspaces/{wid}/artifacts", "/api/workspaces/{wid}/artifacts/{aid}",
        "/api/workspaces/{wid}/runs", "/api/workspaces/{wid}/budget",
        "/api/gates/{gate_id}/approval",
        "/api/graph", "/api/entity/{qname}",
        "/api/workspaces/{wid}/runs/{run_id}/events",
    }
    assert expected <= paths
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_controlplane_router_wiring.py -q`
Expected: FAIL — `ImportError: cannot import name 'controlplane_router'`.

- [ ] **Step 3: Populate `src/cobol_modernizer/controlplane/__init__.py`:**

```python
"""The cockpit control-plane router: workspace/run/gate/artifact/budget + approval
(workspaces.py), graph/entity (graph.py), and the SSE run-events stream (events.py).
api.py includes `controlplane_router` with one line."""
from fastapi import APIRouter

from cobol_modernizer.controlplane.workspaces import router as _workspaces_router
from cobol_modernizer.controlplane.graph import router as _graph_router
from cobol_modernizer.controlplane.events import router as _events_router

controlplane_router = APIRouter()
controlplane_router.include_router(_workspaces_router)
controlplane_router.include_router(_graph_router)
controlplane_router.include_router(_events_router)
```

- [ ] **Step 4: Replace the three temporary includes in `src/cobol_modernizer/api.py` with one.** Delete the six lines added in Tasks 6/7/8:

```python
from cobol_modernizer.controlplane.workspaces import router as _cp_workspaces_router
app.include_router(_cp_workspaces_router)
from cobol_modernizer.controlplane.events import router as _cp_events_router
app.include_router(_cp_events_router)
from cobol_modernizer.controlplane.graph import router as _cp_graph_router
app.include_router(_cp_graph_router)
```

and replace with (at the end of `api.py`):

```python
# --- Cockpit control-plane: workspaces/runs/gates/artifacts/budget/approval,
# read-only graph/entity, and SSE run-events (see controlplane/) -----------------
from cobol_modernizer.controlplane import controlplane_router
app.include_router(controlplane_router)
```

- [ ] **Step 5: Run the wiring test + the consolidated route tests to confirm nothing broke**

Run: `uv run pytest tests/integration/test_controlplane_router_wiring.py tests/integration/test_controlplane_workspaces_api.py tests/integration/test_controlplane_events.py -q`
Expected: all PASS (router wiring 1 + workspaces 7 + events 3 = 11 passed) — the consolidated single include serves the same paths the temp includes did.

- [ ] **Step 6: Commit**

```bash
git add src/cobol_modernizer/controlplane/__init__.py src/cobol_modernizer/api.py tests/integration/test_controlplane_router_wiring.py
git commit -m "feat(controlplane): assemble controlplane_router + wire into api.py (single include)"
```

---

## Task 10: Full-suite verification

**Files:** none (verification).

- [ ] **Step 1: Run the full unit suite**

Run: `uv run pytest tests/unit -q`
Expected: all pass (existing 166 + new control-plane unit tests).

- [ ] **Step 2: Run the integration suite (non-Neo4j path)**

Run: `uv run pytest tests/integration -q`
Expected: control-plane API + events tests pass; graph + other Neo4j/Java tests SKIP without Docker (the pre-existing `test_v2_ingestion_neo4j.py` Java-extractor failure is environmental and unrelated — note it, do not treat as a regression).

- [ ] **Step 3: Confirm the cockpit contract is unbroken**

Run: `cd web && npm test`
Expected: 16 Vitest tests still pass (no web changes were made; this just confirms the DTO shapes the backend now produces still match what the cockpit expects via its own MSW fixtures).

- [ ] **Step 4: Commit (empty marker if nothing changed)**

```bash
git commit --allow-empty -m "chore(controlplane): full suite green (control-plane endpoints wired)"
```

---

## Acceptance criteria (maps to spec)

1. **All 14 endpoints exist + shapes match the cockpit DTOs** — serializer fidelity test (Task 3) + workspace API tests (Task 6) + router-wiring test (Task 8). (spec §1)
2. **POST workspace seeds 11 stages + $50 budget** — Task 6 `test_create_workspace_seeds_stages_and_budget`. (spec §3)
3. **POST approval transitions the gate; waive requires risk** — Task 6 `test_approval_transitions_gate` + `test_waive_requires_risk_accepted` + `test_approval_unknown_gate_404`. (spec §3)
4. **/graph + /entity read-only Neo4j in cockpit shape** — Task 9 integration test. (spec §4)
5. **agent_run_event table + 0004 migration; emit_event ordered + broadcasts** — Task 1 + Task 5. (spec §5)
6. **SSE replays then live-streams, closes on terminal** — Task 7 `test_sse_replays_persisted_events_then_closes_for_terminal_run`. (spec §5)
7. **api.py includes the router, existing endpoints unchanged; suite green** — Task 8 + Task 10. (spec §7)
8. **Cockpit npm test/tsc/build remain green (drop-in for MSW contract)** — Task 10 Step 3. (spec §8)
