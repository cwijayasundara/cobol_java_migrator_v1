# Running the Cockpit against the real backend

The FastAPI control plane (`src/cobol_modernizer/api.py`) serves every endpoint the
Next.js cockpit (`web/`) calls, backed by **Postgres** (workspaces/runs/gates/
artifacts/budget/approvals/run-events) and read-only **Neo4j** (`/api/graph`,
`/api/entity`). The endpoints connect via env-configured dependencies
(`controlplane/deps.py`): `get_session` → `POSTGRES_URL`, `get_neo4j` → `NEO4J_*`.

## 1. Services

The repo ships `docker-compose.yml` with `postgres:16`, `neo4j:5.24-enterprise`,
and `minio`. Bring them up (or point the env below at existing instances):

```bash
docker compose up -d postgres neo4j
```

If host ports 5432/7687/7474 are already taken, remap them in a compose override
and update `POSTGRES_URL`/`NEO4J_URI` accordingly.

## 2. Environment

```bash
cp .env.example .env        # creds already match docker-compose (cobol/devpassword)
```

The control plane and Alembic both `load_dotenv()`, so `.env` is picked up
automatically (an exported shell var still wins over `.env`).

## 3. Migrate + seed

```bash
PYTHONPATH=src uv run alembic -c alembic.ini upgrade head   # creates all 13 tables
PYTHONPATH=src uv run python -m cobol_modernizer.controlplane.seed   # demo CardDemo workspace
```

`seed` is idempotent (skips if the `aws-mf-carddemo` workspace already exists) and
mirrors the cockpit's fixture: a workspace + 11 journey stages + a BRD groundedness
gate + a $50 budget + one running BRD agent run (with events) + a BRD artifact.

## 4. Run the API + cockpit

```bash
PYTHONPATH=src uv run uvicorn cobol_modernizer.api:app --port 8000   # control plane
cd web && npm run dev                                                # cockpit on :3000
```

`web/next.config.ts` proxies `/api/*` → `http://localhost:8000`, so the cockpit at
http://localhost:3000/workspaces reads live data.

## 5. Smoke check

```bash
curl -s localhost:8000/api/workspaces            # the seeded CardDemo workspace
curl -s "localhost:8000/api/workspaces/<id>/stages"   # 11 stages
curl -s "localhost:8000/api/graph?repo=aws-mf-carddemo&limit=50"   # read-only Neo4j
```

## Notes / not-yet-wired

- **Agent execution → SSE:** `controlplane/events.py:emit_event(session, ...)` is the
  seam a server-side agent executor calls to append run events (which then replay +
  live-stream over `/runs/{id}/events`). Hooking it into the actual SDK agent harness
  so real runs emit events is future work; `seed` emits a couple of demo events.
- **Graph data:** `/api/graph` + `/api/entity` are read-only over whatever the
  ingestion pipeline has loaded into Neo4j for the repo; an empty graph returns
  `{"nodes": [], "links": []}`.
- Tests never need live services: `get_session` is overridden with in-memory SQLite
  and `get_neo4j` with a Neo4j testcontainer.
