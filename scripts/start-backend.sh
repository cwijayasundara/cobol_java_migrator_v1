#!/usr/bin/env bash
#
# Start the COBOL-modernizer control-plane backend with ONE command.
#
# Loads .env (creating it from .env.example on first run), brings up Postgres +
# Neo4j via docker compose, applies the Alembic migrations, seeds a demo
# workspace, and runs the FastAPI app on $BACKEND_PORT (default 8000).
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

# --- 2. Backing services (Postgres + Neo4j) ----------------------------------
echo "→ starting Postgres + Neo4j (docker compose up -d)…"
if ! docker compose up -d postgres neo4j; then
  echo "✗ docker compose failed. If a host port is already in use, set"
  echo "  POSTGRES_PORT / NEO4J_BOLT_PORT / NEO4J_HTTP_PORT in .env (and update"
  echo "  POSTGRES_URL / NEO4J_URI to match), then re-run."
  exit 1
fi

printf "→ waiting for Postgres"
until docker compose exec -T postgres pg_isready -U "${POSTGRES_USER:-cobol}" >/dev/null 2>&1; do
  printf "."; sleep 1
done
echo " ready"

# best-effort Neo4j bolt wait (non-fatal — only /api/graph + /api/entity need it)
neo_hostport="${NEO4J_URI#*://}"
neo_host="${neo_hostport%%:*}"; neo_port="${neo_hostport##*:}"
neo_host="${neo_host:-localhost}"; case "$neo_port" in *[!0-9]*|"") neo_port=7687;; esac
printf "→ waiting for Neo4j (bolt %s)" "$neo_port"
for _ in $(seq 1 30); do
  if (exec 3<>"/dev/tcp/${neo_host}/${neo_port}") 2>/dev/null; then exec 3>&- 3<&-; echo " ready"; break; fi
  printf "."; sleep 1
done
echo ""

# --- 3. Schema + demo data ---------------------------------------------------
echo "→ applying migrations (alembic upgrade head)…"
PYTHONPATH=src uv run alembic -c alembic.ini upgrade head

echo "→ seeding demo workspace (idempotent)…"
PYTHONPATH=src uv run python -m cobol_modernizer.controlplane.seed

# --- 4. Run ------------------------------------------------------------------
echo "→ control plane → http://localhost:${BACKEND_PORT}   (Ctrl-C to stop)"
exec env PYTHONPATH=src uv run uvicorn cobol_modernizer.api:app \
  --host 0.0.0.0 --port "${BACKEND_PORT}"
