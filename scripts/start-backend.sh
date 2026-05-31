#!/usr/bin/env bash
#
# Start the COBOL-modernizer control-plane backend with ONE command.
#
# Loads .env (creating it from .env.example on first run), brings up Postgres +
# Neo4j via docker compose, applies the Alembic migrations, seeds a demo
# workspace, and runs the FastAPI app on $BACKEND_PORT (default 8000).
#
# Host ports are chosen automatically: it reuses the ports an already-running
# stack publishes, otherwise it picks the next FREE port (so it just works even
# when 5432/7687/7474 are taken by other local services) and derives the
# connection URLs from them — no .env editing ever required.
#
# Idempotent — safe to re-run. Stop with Ctrl-C (the DB/Neo4j containers keep
# running; `docker compose down` to stop them).
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# --- 1. Environment ----------------------------------------------------------
if [ ! -f .env ]; then
  cp .env.example .env
  echo "→ created .env from .env.example"
fi
set -a; . ./.env; set +a
BACKEND_PORT="${BACKEND_PORT:-8000}"

command -v docker >/dev/null || { echo "✗ docker not found — install Docker and retry"; exit 1; }
command -v uv >/dev/null     || { echo "✗ uv not found — see https://docs.astral.sh/uv/"; exit 1; }

# --- 2. Choose free host ports (reuse-if-running, else next free) ------------
# The containers' credentials are fixed by docker-compose.yml; we derive the
# connection URLs from whatever host ports we land on, so no .env edits are ever
# needed even when the defaults clash with another local service.
PG_USER="${POSTGRES_USER:-cobol}"; PG_PASS="${POSTGRES_PASSWORD:-devpassword}"; PG_DB="${POSTGRES_DB:-cobol_modernizer}"
NEO_USER="${NEO4J_USER:-neo4j}";   NEO_PASS="${NEO4J_PASSWORD:-devpassword}"

_busy()      { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }            # 0 = something is listening
_free_from() { local p="$1"; while _busy "$p"; do p=$((p + 1)); done; printf '%s' "$p"; }
_published() { docker compose port "$1" "$2" 2>/dev/null | sed -n 's/.*:\([0-9]\{1,\}\)$/\1/p' | head -1; }
_choose()    { local cur; cur="$(_published "$1" "$2")"; [ -n "$cur" ] && printf '%s' "$cur" || _free_from "$3"; }

POSTGRES_PORT="$(_choose postgres 5432 "${POSTGRES_PORT:-5432}")"
NEO4J_BOLT_PORT="$(_choose neo4j 7687 "${NEO4J_BOLT_PORT:-7687}")"
NEO4J_HTTP_PORT="$(_choose neo4j 7474 "${NEO4J_HTTP_PORT:-7474}")"
export POSTGRES_PORT NEO4J_BOLT_PORT NEO4J_HTTP_PORT

# Derived connection settings override whatever .env held so the app + alembic
# talk to the host ports we actually mapped.
export POSTGRES_URL="postgresql+psycopg://${PG_USER}:${PG_PASS}@localhost:${POSTGRES_PORT}/${PG_DB}"
export NEO4J_URI="bolt://localhost:${NEO4J_BOLT_PORT}"
export NEO4J_USER="$NEO_USER" NEO4J_PASSWORD="$NEO_PASS"
echo "→ host ports: postgres=${POSTGRES_PORT}  neo4j bolt=${NEO4J_BOLT_PORT} http=${NEO4J_HTTP_PORT}"

# --- 3. Backing services (Postgres + Neo4j) ----------------------------------
echo "→ starting Postgres + Neo4j (docker compose up -d)…"
docker compose up -d postgres neo4j

printf "→ waiting for Postgres"
until docker compose exec -T postgres pg_isready -U "${PG_USER}" >/dev/null 2>&1; do
  printf "."; sleep 1
done
echo " ready"

# best-effort Neo4j bolt wait (non-fatal — only /api/graph + /api/entity need it)
printf "→ waiting for Neo4j (bolt %s)" "$NEO4J_BOLT_PORT"
for _ in $(seq 1 45); do
  if _busy "$NEO4J_BOLT_PORT"; then echo " ready"; break; fi
  printf "."; sleep 1
done
echo ""

# --- 4. Schema + demo data ---------------------------------------------------
echo "→ applying migrations (alembic upgrade head)…"
PYTHONPATH=src uv run alembic -c alembic.ini upgrade head

echo "→ seeding demo workspace (idempotent)…"
PYTHONPATH=src uv run python -m cobol_modernizer.controlplane.seed

# --- 5. Run ------------------------------------------------------------------
echo "→ control plane → http://localhost:${BACKEND_PORT}   (Ctrl-C to stop)"
exec env PYTHONPATH=src uv run uvicorn cobol_modernizer.api:app \
  --host 0.0.0.0 --port "${BACKEND_PORT}"
