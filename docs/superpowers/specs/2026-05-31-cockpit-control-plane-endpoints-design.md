# Cockpit Control-Plane Endpoints — Design Spec

**Date:** 2026-05-31
**Status:** Approved (brainstorming)
**Branch:** `cockpit-control-plane-endpoints`

## Goal

Implement the FastAPI control-plane HTTP endpoints that the UI Cockpit (`web/`)
already calls through `web/src/lib/api.ts`. Today those endpoints are mocked by
MSW in the cockpit's tests; the real `src/cobol_modernizer/api.py` only has the
slice, equivalence, and canary-routing endpoints and is otherwise stateless. This
work makes the cockpit run against a live backend by wiring the existing Postgres
ORM models, the read-only Neo4j graph layer, and a new run-event stream into the
control plane.

The **contract is fixed** by the cockpit's DTOs (`web/src/lib/types.ts`) and the
canonical MSW fixtures (`web/src/test/fixtures/controlplane.ts`): the backend's
JSON responses must be drop-in identical so the cockpit works unchanged.

## Scope

Full scope (chosen): all three tiers — DB-backed CRUD, live-Neo4j graph, and SSE
run events (which requires a new event source: an `agent_run_event` table + an
in-process broadcaster).

Endpoints (all under `/api`):

| Method | Path | Backing |
|---|---|---|
| GET | `/workspaces` | Postgres |
| POST | `/workspaces` | Postgres (also seeds 11 stages + budget) |
| GET | `/workspaces/{id}` | Postgres |
| GET | `/workspaces/{id}/stages` | Postgres |
| GET | `/workspaces/{id}/gates` | Postgres |
| GET | `/workspaces/{id}/artifacts` | Postgres |
| GET | `/workspaces/{id}/artifacts/{aid}` | Postgres |
| GET | `/workspaces/{id}/runs` | Postgres |
| POST | `/workspaces/{id}/runs` | Postgres |
| GET | `/workspaces/{id}/budget` | Postgres |
| POST | `/gates/{gateId}/approval` | Postgres (inserts Approval, transitions Gate) |
| GET | `/graph?repo=&limit=` | Neo4j (read-only) |
| GET | `/entity/{qname}` | Neo4j (read-only) |
| GET | `/workspaces/{id}/runs/{runId}/events` | SSE (replay + live broadcast) |

Out of scope: re-wiring the Phase-6 canary `flip`/`rollback` endpoints to persist
`Gate`/`Approval`/`CanaryRoute` rows (they stay in-memory; only the cockpit's
`/gates/{id}/approval` endpoint is DB-backed here). No agent-execution changes —
`emit_event` is the seam an executor would call, but wiring it into the SDK
harness is future work.

## Architecture

A new focused package `src/cobol_modernizer/controlplane/` exposes one
`APIRouter`, which `api.py` includes with a single line. This keeps the
already-multi-concern `api.py` from ballooning and matches the repo's
package-per-concern style (`seam/`, `planner/`, `deploy/`).

```
src/cobol_modernizer/controlplane/
├── __init__.py          # builds + exports `controlplane_router` (includes the sub-routers)
├── deps.py              # get_session (Postgres), get_neo4j (read-only client) FastAPI deps
├── serializers.py       # pure ORM -> dict DTOs matching web/src/lib/types.ts exactly
├── stages.py            # canonical 11 journey stage_keys + gate mapping (backend SOT)
├── workspaces.py        # workspaces/stages/gates/artifacts/runs/budget + approval routes
├── graph.py             # /graph + /entity routes (read-only Cypher)
└── events.py            # AgentRunEvent emitter + Broadcaster + SSE endpoint
```

`api.py` change: `from cobol_modernizer.controlplane import controlplane_router` +
`app.include_router(controlplane_router)`.

### 1. DB access + dependencies (`deps.py`)

- `get_session() -> Iterator[Session]` — FastAPI dependency yielding a SQLAlchemy
  `Session` from a lazily-constructed module engine (`db.make_engine()` reading
  `POSTGRES_URL`). Commits on success, rolls back on exception, always closes
  (reuses the `db.session_scope` semantics).
- `get_neo4j() -> Iterator[Neo4jClient]` — yields an app-managed read-only
  `Neo4jClient` built from env (`NEO4J_URI`/`NEO4J_USER`/`NEO4J_PASSWORD`).
- Both are overridable in tests via `app.dependency_overrides`: unit tests point
  `get_session` at an in-memory sqlite engine (`StaticPool`,
  `Base.metadata.create_all`, seeded fixtures); integration tests point
  `get_neo4j` at the `neo4j_graph` testcontainer fixture.

### 2. DTO serializers (`serializers.py`)

Pure functions `workspace_dto / stage_dto / run_dto / artifact_dto / gate_dto /
approval_dto / budget_dto`, each ORM-instance → `dict`, producing JSON that
matches `web/src/lib/types.ts` field-for-field:
- `Numeric(12,6)` columns (`total_cost_usd`, `cap_usd`, `spent_usd`) → `float`.
- `DateTime` columns → ISO-8601 strings (`.isoformat()`).
- `JSON` columns (`evidence_map`, `threshold`, `result`, `perf_baseline`) → passthrough.
- `BigInteger` token columns → `int`.

A serializer-fidelity test loads the canonical fixtures, builds the matching ORM
rows, serializes, and asserts equality against the documented DTO shapes (the same
shapes the cockpit's MSW fixtures use).

### 3. DB-backed routes (`workspaces.py`)

- `GET /workspaces` → `[workspace_dto]`; `GET /workspaces/{id}` → `workspace_dto`
  (404 if missing).
- `POST /workspaces` body `{name, repo_slug, created_by}` → creates the
  `Workspace`, **seeds the canonical 11 `journey_stage` rows** (ordinal 0..10,
  first stage `running`, rest `pending`) and a **workspace-scoped `Budget`**
  (`scope="workspace"`, `cap_usd=50.0`, `spent_usd=0`), returns `workspace_dto`.
- `GET /workspaces/{id}/stages|gates|artifacts|runs` → lists, ordered
  (stages by ordinal, runs by `started_at` desc, artifacts by `created_at` desc).
- `GET /workspaces/{id}/artifacts/{aid}` → `artifact_dto` (404 if missing).
- `GET /workspaces/{id}/budget` → workspace-scoped `budget_dto` (404 if none).
- `POST /workspaces/{id}/runs` body `{stage_key, role, started_by}` → creates an
  `AgentRun` (`status="running"`, token counters 0, `model` from
  `cost.tiering.resolve_model(role)`), linked to the stage with that `stage_key`,
  returns `run_dto`.
- `POST /gates/{gateId}/approval` body `{decision, approver_email, approver_role,
  risk_accepted, rationale}` → inserts an `Approval` row and transitions the
  `Gate.status`: `approved`→`passed`, `rejected`→`failed`,
  `waived_with_risk`→`waived` (and requires `risk_accepted=true` for waive, else
  400). Returns `approval_dto`. 404 if the gate is missing.

### 4. Graph routes (`graph.py`)

Two new **read-only** Cypher reads added to `queries.py` (or `graph_ops`):
- `graph_overview(client, repo, limit)` → `{nodes:[{id,name,kind,file,summary}],
  links:[{source,target,type}]}` — nodes capped at `limit`, links among those nodes.
- `entity_detail(client, qname)` → `{entity:{...}, incoming:[{source,source_kind,
  relationship}], outgoing:[{target,target_kind,relationship}]}`.
- `GET /graph?repo=&limit=300` and `GET /entity/{qname}` call these and return the
  cockpit-shaped JSON; 404 if the entity is unknown.
- Tests are `@pytest.mark.integration` (skip without Docker/Neo4j), seeding a tiny
  subgraph via the `neo4j_graph` fixture and asserting the shape.

### 5. SSE events (`events.py`) + `agent_run_event` table

New ORM model in `persistence/tables.py`:
```
AgentRunEvent
  id          str  PK (uuid)
  run_id      str  FK -> agent_run.id ON DELETE CASCADE
  seq         int  NOT NULL
  ts          DateTime(tz) default now
  type        str  NOT NULL   # plan|tool_call|tool_result|cost|result|approval_request|failed|killed
  summary     str  NOT NULL
  detail      JSON default {}
  UNIQUE (run_id, seq)
```
+ Alembic migration `0004_agent_run_event` (chains from `0003_deploy`).

- `Broadcaster` — process-local async pub/sub: `subscribe(run_id) ->
  (asyncio.Queue, unsubscribe)` and `publish(run_id, event_dict)` fan-out to all
  subscriber queues for that run. A module singleton.
- `emit_event(session, *, run_id, type, summary, detail=None) -> dict` — computes
  the next `seq` (`max(seq)+1` for the run), inserts the row, flushes, and
  `publish`es the event dict to the broadcaster. Returns the event dict (matching
  the cockpit `AgentEvent` shape: `{type, run_id, seq, ts, summary, detail}`).
- `GET /workspaces/{id}/runs/{runId}/events` → `EventSourceResponse` over an async
  generator that:
  1. replays all persisted `agent_run_event` rows for `runId` in `seq` order as
     SSE frames (resume/checkpoint);
  2. if the run's `status` is terminal (`succeeded|failed|killed`) → stop;
  3. else `subscribe` to the broadcaster and yield live frames until a terminal
     event arrives or the client disconnects, then `unsubscribe`.
- Each SSE frame's `data:` is the JSON of the `AgentEvent` dict.

### 6. Testing

- **Unit** (`tests/integration/test_controlplane_api.py` using sqlite +
  `dependency_overrides`, plus focused unit tests):
  - every DB route (list/get/create), 404s, ordering;
  - POST-workspace seeds 11 stages + budget;
  - POST-approval transitions the gate per decision; waive without `risk_accepted`
    → 400;
  - serializer shape-match against the canonical fixtures;
  - `emit_event` seq increment + row insert + returned dict shape;
  - `Broadcaster` publish/subscribe fan-out;
  - SSE replay-and-close for a terminal run (finite stream read via TestClient).
- **Integration** (`@pytest.mark.integration`): `/graph` + `/entity` against the
  `neo4j_graph` testcontainer.

A shared pytest fixture builds the sqlite engine, seeds the canonical workspace
(`ws-1` CardDemo + 11 stages + brd gate + budget + run + brd artifact mirroring
`web/src/test/fixtures/controlplane.ts`), overrides `get_session`, and yields a
`TestClient`; teardown clears `app.dependency_overrides`.

### 7. Dependencies / wiring

- Declare `sse-starlette>=2.1` in `pyproject.toml` (currently only transitively
  present).
- `api.py`: add `app.include_router(controlplane_router)` (one line + import).
- No change to the existing slice/equivalence/canary endpoints.

## Non-negotiables honored

- **Neo4j read-only**: graph endpoints only call read queries; no writes.
- **Source-of-truth split**: workspace/run/gate/budget/event state in Postgres;
  code graph in Neo4j; the cockpit still reads everything through `lib/api.ts`.
- **Token economy**: `budget_dto` surfaces the cap (not just spend); `run_dto`
  carries token counters + `total_cost_usd`.
- **Attributed gates**: `/gates/{id}/approval` records `approver_email` +
  `approver_role` + `rationale` and transitions the gate (RBAC attribution).
- **Agent execution stays server-side**: the cockpit only *reads* the event
  stream; `emit_event` is called by server-side code, never the browser.

## Acceptance criteria

1. All 14 endpoints exist and return JSON matching `web/src/lib/types.ts` /
   the cockpit MSW fixtures (a fidelity test proves shape-equality).
2. POST workspace seeds the 11 canonical stages + a $50-cap workspace budget.
3. POST approval inserts an attributed `Approval` and transitions the `Gate`
   (`passed`/`failed`/`waived`); waive requires `risk_accepted`.
4. `/graph` + `/entity` return read-only Neo4j data in the cockpit's
   `GraphData`/`EntityDetail` shape (integration-gated).
5. `agent_run_event` table + `0004` migration exist; `emit_event` appends ordered
   events and publishes to the broadcaster.
6. The SSE endpoint replays persisted events then live-streams new ones, closing
   on terminal status; replay-and-close is unit-tested for a terminal run.
7. `api.py` includes the new router with no change to existing endpoints; full
   Python test suite green (the pre-existing Java-extractor integration failure
   excepted).
8. The cockpit's `npm test`/`tsc`/`build` remain green (no web changes needed —
   the backend is a drop-in for the MSW contract).
