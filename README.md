# COBOL → Java/Spring Boot Migration Platform

A **generic, graph-grounded, agent-driven COBOL → Java/Spring Boot modernization
platform**. Nothing is tied to a specific app — drop your COBOL into
`source_code_to_analyse/` (git-ignored) and the toolchain discovers it. AWS CardDemo
is a convenient public test workload.

The platform is a **FastAPI control plane** (`src/cobol_modernizer/`) plus an
**11-stage Next.js cockpit** (`web/`), backed by **Neo4j** (the deterministic code
graph — source of truth), **Postgres** (run/audit/RBAC/version state), and **MinIO**
(artifacts). Agent execution stays server-side; the cockpit is a thin client that
reads everything through the control plane.

> **Status:** the full roadmap is implemented — Phase 0 (baseline/persistence/cost)
> through Phase 6 (deployment & canary), the cross-cutting UI cockpit, and the
> cockpit↔backend control-plane endpoints. See `docs/plans/INDEX.md` for the
> roadmap and `docs/plans/*` for the per-phase plans.

---

## Quick start (two scripts)

Two one-shot scripts bring the whole thing up — no piecemeal commands.

```bash
# 1. Backend: loads .env (creates it from .env.example on first run), starts
#    Postgres + Neo4j, applies migrations, seeds a demo workspace, runs the API.
./scripts/start-backend.sh        # → http://localhost:8000

# 2. Cockpit UI (in a second terminal): installs web deps on first run, runs the
#    Next.js dev server. It proxies /api/* → http://localhost:8000.
./scripts/start-ui.sh             # → http://localhost:3000
```

Open **http://localhost:3000/workspaces** — the seeded **CardDemo** workspace appears
with its 11-stage journey, gate/cost pills, agent console, and evidence drawer.

Both scripts are **idempotent** (safe to re-run) and read every setting from `.env`.
Stop the backend with `Ctrl-C`; the containers keep running (`docker compose down`
to stop them, `down -v` to also drop the data volumes).

### Prerequisites

| Tool | Version | For |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | ≥ 0.5 | Python 3.12 env + the backend |
| Docker | running | Postgres + Neo4j (+ MinIO) via `docker-compose.yml` |
| Node.js | ≥ 18 | the cockpit (`web/`) |
| JDK 25 + Maven 3.9+ | — | **only** to build the ProLeap COBOL extractor (ingesting real COBOL); not needed to run the cockpit against the seed |

### Port conflicts

Default host ports are Postgres `5432`, Neo4j `7687`/`7474`, API `8000`, UI `3000`.
**`start-backend.sh` handles Postgres/Neo4j port conflicts automatically** — it reuses
the ports an already-running stack publishes, otherwise picks the next free port and
derives `POSTGRES_URL`/`NEO4J_URI` from it, so you never edit `.env` for this. It
prints the chosen ports, e.g. `→ host ports: postgres=5432 neo4j bolt=7687 http=7475`.

To *pin* specific ports instead, set them in `.env` (`POSTGRES_PORT`,
`NEO4J_BOLT_PORT`, `NEO4J_HTTP_PORT`) — those become the starting point and are still
auto-bumped only if busy. The **API port** (`BACKEND_PORT`, default 8000) is *not*
auto-changed because the cockpit proxies `/api` → `:8000`; free 8000 or change both
sides. See also `docs/running-the-cockpit.md`.

---

## What's in the box

| Area | Where | Notes |
|---|---|---|
| Deterministic analysis core | `cobol/`, `parser.py`, `ingestion.py`, `neo4j_client.py`, `schema.py` | ProLeap COBOL → single `schemaVersion=2` JSON contract → Neo4j graph |
| v2 graph enrichment (Phase 1) | `queries.py`, `agent/graph_ops.py` | READS/WRITES/EXECUTES_CICS/SQL + DataItem nodes; reader/writer Cypher |
| BRD pipeline + groundedness gate | `brd/`, `agent/brd_judge.py` | map/reduce BRD with lineage-checked judge |
| Thin vertical slice + dark launch (Phase 2) | `slice/`, `darklaunch/` | account-view Spring Boot slice (Spring Boot 4.0.6 / Java 25) |
| Equivalence Lab (Phase 3) | `equivalence/` | golden-master diff with COMP-3 / scale tolerance + identity-drift |
| Seam engine + increment planner (Phase 4) | `seam/`, `planner/` | ranked seams + acyclic INVEST story DAG, all Cypher (no LLM in scoring) |
| Design + codegen workbench (Phase 5) | `design/`, `codegen/`, `mimic/` | service design/ADRs, TDD codegen + repair loop, Legacy Mimic write-back |
| Deployment + canary (Phase 6) | `deploy/` | routing enabling-point, proven rollback, fitness functions, stoppable-safe |
| Cost guardrails | `cost/tiering.py`, `cost/policy.py` | model tiering + fail-closed caps with a kill-switch |
| Persistence | `persistence/` | Postgres run/audit/RBAC (Alembic; 13 tables incl. `agent_run_event`) |
| Control plane (HTTP/SSE) | `api.py`, `controlplane/` | the cockpit's backend — see below |
| Cockpit UI | `web/` | Next.js 15 / React 19 / Tailwind 3.4, five-region shell + 9 screens |

### Control-plane endpoints (`controlplane/`)

The cockpit talks to these (all under `/api`), backed by Postgres + read-only Neo4j:

- `GET /repos` — discover local COBOL repos under `source_code_to_analyse/` (the
  Portfolio's "Available repositories" picker; pick any to start a workspace, no default
  repo). Only dirs that actually contain COBOL are listed. Scan root overridable via
  `COBOL_SOURCE_ROOT`.
- `GET/POST /workspaces`, `GET /workspaces/{id}`
- `GET /workspaces/{id}/{stages,gates,artifacts,runs,budget}`, `GET .../artifacts/{aid}`
- `POST /workspaces/{id}/parse` — the **Parse** stage's "Run parse" button: runs the
  ProLeap extractor on the workspace's repo and ingests the code graph into Neo4j
  (deterministic, no LLM), marking the parse+graph stages passed. Needs `JAVA_HOME` +
  the extractor JAR (start-backend.sh auto-sets both). The later LLM stages
  (blueprint/seams/design/build) still need an Anthropic key + the agent harness.
- `POST /workspaces/{id}/runs` · `POST /gates/{id}/approval` (attributed RBAC gate)
- `GET /graph?repo=&limit=` · `GET /entity/{qname}` (read-only Neo4j)
- `GET /workspaces/{id}/runs/{runId}/events` (SSE: replay persisted events + live stream)

`controlplane/seed.py` (`python -m cobol_modernizer.controlplane.seed`) creates the
demo workspace `start-backend.sh` shows. `controlplane/events.py:emit_event(...)` is
the seam a server-side agent executor calls to feed the SSE stream (wiring it into the
live agent harness is the next piece of work).

---

## Configuration

`scripts/start-backend.sh` creates `.env` from `.env.example` on first run; edit `.env`
to change anything. Key groups (full list in `.env.example`):

- **LLM / Anthropic** — `ANTHROPIC_API_KEY` + per-role model overrides (defaults in
  `cost/tiering.py`). Not needed just to run the cockpit against seeded data.
- **Cost caps** — `COBOL_MOD_WORKSPACE_CAP_USD`, `COBOL_MOD_RUN_CAP_USD`.
- **Neo4j / Postgres / MinIO** — connection URLs + the `*_PORT` overrides above.
- **COBOL extractor** — `COBOL_EXTRACTOR_JAR`, `JAVA_HOME`, `COBOL_MOD_COPYBOOK_DIRS`
  (only for ingesting real COBOL; see below).

---

## Tests

```bash
uv run --extra dev pytest tests/unit -q          # fast unit suite (no Docker/JAR)
uv run --extra dev pytest -q                      # + integration (Docker for Neo4j/Postgres testcontainers)
cd web && npm test                                # cockpit (Vitest, MSW-mocked)
```

Integration tests spin up throwaway Neo4j/Postgres containers and `skip` (not fail)
when Docker/Java/JAR are unavailable. One pre-existing integration test
(`test_v2_ingestion_neo4j.py`) fails only when the Java extractor JAR is built but the
local Java toolchain rejects it — environmental, not a code regression.

> Note: `uv run pytest` may resolve an ephemeral Python that lacks the dev
> `testcontainers` extra, causing Neo4j/Postgres integration tests to **skip**. To run
> them for real: `uv pip install --python .venv/bin/python testcontainers docker pytest pytest-asyncio`
> then `.venv/bin/python -m pytest ...`.

---

## Ingesting real COBOL (analysis core)

Put COBOL under `source_code_to_analyse/` (git-ignored). To ingest/benchmark you need
the ProLeap extractor JAR:

```bash
export JAVA_HOME=/opt/homebrew/opt/openjdk@25/libexec/openjdk.jdk/Contents/Home   # your JDK 25
cd tools/cobol-extractor && JAVA_HOME=$JAVA_HOME mvn -q clean package && cd -
# → tools/cobol-extractor/target/cobol-extractor.jar  (emits schemaVersion=2)
```

For example, AWS CardDemo:

```bash
git clone https://github.com/aws-samples/aws-mainframe-modernization-carddemo.git \
  source_code_to_analyse/aws-mf-mod-carddemo
```

One-command baseline benchmark (real extractor → report):

```bash
COBOL_EXTRACTOR_JAR="$PWD/tools/cobol-extractor/target/cobol-extractor.jar" \
JAVA_HOME=/opt/homebrew/opt/openjdk@25/libexec/openjdk.jdk/Contents/Home \
COBOL_MOD_COPYBOOK_DIRS=app/cpy,app/cpy-bms PYTHONPATH=src \
uv run python -m cobol_modernizer.cli baseline \
  --repo ./source_code_to_analyse/aws-mf-mod-carddemo --out ./benchmark_out/baseline.json
```

> **If `COBOL_EXTRACTOR_JAR`/`JAVA_HOME` are missing, the parser silently degrades to
> zero entities** — a misleading "pass". `PYTHONPATH=src` is needed for `python -m …`
> (pytest sets it automatically).

---

## Manual backend bring-up (what start-backend.sh automates)

```bash
docker compose up -d postgres neo4j
cp .env.example .env
PYTHONPATH=src uv run alembic -c alembic.ini upgrade head     # 13 tables
PYTHONPATH=src uv run python -m cobol_modernizer.controlplane.seed
PYTHONPATH=src uv run uvicorn cobol_modernizer.api:app --port 8000
```

`alembic` needs `PYTHONPATH=src` (the package is src-layout, not pip-installed).

---

## Layout

```
src/cobol_modernizer/
  api.py                         # FastAPI control plane (includes every router)
  controlplane/                  # cockpit endpoints: deps, serializers, stages,
                                 #   workspaces, graph, events(SSE), seed
  contract/, cobol/, parser.py, neo4j_client.py, schema.py, ingestion*.py, queries.py
  brd/, slice/, darklaunch/, equivalence/, seam/, planner/, design/, codegen/, mimic/, deploy/
  cost/ (tiering, policy)        # model tiering + fail-closed caps / kill-switch
  persistence/ (tables, db, migrations/)   # Postgres run/audit/RBAC + Alembic (0001..0004)
  agent/ (harness, graph_ops, brd_judge, …)
  cli.py
web/                             # Next.js 15 cockpit (5-region shell + 9 stage screens)
tools/cobol-extractor/           # ProLeap Java extractor (emits schemaVersion=2)
scripts/                         # start-backend.sh, start-ui.sh
docs/plans/                      # per-phase implementation plans + INDEX.md
docs/running-the-cockpit.md      # backend bring-up detail
tests/unit/, tests/integration/
```

---

## Troubleshooting

- **Port already in use** → `start-backend.sh` auto-picks a free port; if a clash still
  surfaces, re-run it (or pin ports via the `*_PORT` vars in `.env`). `BACKEND_PORT`
  (8000) is not auto-changed — free 8000 or change the cockpit proxy too.
- **`/api/graph` → 503 / Neo4j `Unauthorized` / `AuthenticationRateLimit`** → the app's
  `NEO4J_PASSWORD` doesn't match the running Neo4j. Neo4j only applies `NEO4J_AUTH` when
  its **data volume is empty**, so changing the password later doesn't re-apply. Fix:
  set `NEO4J_PASSWORD` in `.env` to the volume's password, **or** reset the volume with
  `docker compose down -v` (the graph is re-ingestable), then re-run
  `./scripts/start-backend.sh`. After fixing, restart the backend so it picks up the
  new password (env is read at process start). The endpoints now 503 (not 500) on a
  graph outage, so the cockpit stays usable — the graph panel is just empty.
- **Cockpit shows no data** → the backend isn't running or the seed didn't run; re-run
  `./scripts/start-backend.sh` (the seed is idempotent).
- **Stray `"<name> 2.ext"` files** appear from cloud-sync/Finder conflict copies and are
  untracked; they once broke Alembic (duplicate revision id). List them with
  `git ls-files --others --exclude-standard | grep ' 2\.'` then delete the listed files.
