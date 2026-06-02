#!/usr/bin/env bash
#
# Start the COBOL-modernizer control-plane backend with ONE command.
#
# Loads .env (creating it from .env.example on first run), brings up Postgres +
# Neo4j via docker compose, applies the Alembic migrations, seeds a demo
# workspace, and runs the FastAPI app on $BACKEND_PORT (default 8005).
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
BACKEND_PORT="${BACKEND_PORT:-8005}"

command -v docker >/dev/null || { echo "✗ docker not found — install Docker and retry"; exit 1; }
command -v uv >/dev/null     || { echo "✗ uv not found — see https://docs.astral.sh/uv/"; exit 1; }

_busy() {                                                                  # 0 = something is listening
  if command -v lsof >/dev/null; then
    lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  elif command -v nc >/dev/null; then
    nc -z 127.0.0.1 "$1" >/dev/null 2>&1 || nc -z localhost "$1" >/dev/null 2>&1
  else
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
  fi
}

# Do not start a shadowed backend. macOS can allow one process on 127.0.0.1:$BACKEND_PORT
# and another on *:$BACKEND_PORT; browsers/Next's localhost proxy hit the loopback
# process, causing confusing 404s from the wrong API. Check before any Docker calls so
# a port conflict is reported even when Docker is unavailable to this shell.
if _busy "$BACKEND_PORT"; then
  echo "✗ another process is already listening on localhost:${BACKEND_PORT};"
  echo "  the cockpit proxy would hit that process instead of this control plane."
  echo "  Stop it, or set BACKEND_PORT and update web/next.config.ts to match."
  if command -v lsof >/dev/null; then
    lsof -nP -iTCP:"$BACKEND_PORT" -sTCP:LISTEN || true
  fi
  exit 1
fi

# The 'parse' stage runs the ProLeap COBOL extractor (Java). Make it work out of
# the box: resolve a real JDK (the macOS /usr/bin/java stub is not enough) and the
# built extractor JAR, exporting both for the API process. Non-fatal if absent —
# only the parse action needs them.
if [ -z "${JAVA_HOME:-}" ] || [ ! -x "${JAVA_HOME:-}/bin/java" ]; then
  for _jh in /opt/homebrew/opt/openjdk@25/libexec/openjdk.jdk/Contents/Home \
             /opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home \
             "$(/usr/libexec/java_home 2>/dev/null || true)"; do
    if [ -n "$_jh" ] && [ -x "$_jh/bin/java" ]; then export JAVA_HOME="$_jh"; break; fi
  done
fi
: "${COBOL_EXTRACTOR_JAR:=tools/cobol-extractor/target/cobol-extractor.jar}"
case "$COBOL_EXTRACTOR_JAR" in /*) ;; *) COBOL_EXTRACTOR_JAR="$ROOT/$COBOL_EXTRACTOR_JAR";; esac
export COBOL_EXTRACTOR_JAR
if [ -n "${JAVA_HOME:-}" ] && [ -f "$COBOL_EXTRACTOR_JAR" ]; then
  echo "→ COBOL extractor ready (JAVA_HOME=$JAVA_HOME)"
else
  echo "⚠ COBOL extractor not fully available (JAVA_HOME='${JAVA_HOME:-}', jar='$COBOL_EXTRACTOR_JAR')."
  echo "  The 'parse' stage needs JDK 25 + the built JAR (cd tools/cobol-extractor && mvn -q package)."
fi

# --- 2. Choose free host ports (reuse-if-running, else next free) ------------
# The containers' credentials are fixed by docker-compose.yml; we derive the
# connection URLs from whatever host ports we land on, so no .env edits are ever
# needed even when the defaults clash with another local service.
PG_USER="${POSTGRES_USER:-cobol}"; PG_PASS="${POSTGRES_PASSWORD:-devpassword}"; PG_DB="${POSTGRES_DB:-cobol_modernizer}"
NEO_USER="${NEO4J_USER:-neo4j}";   NEO_PASS="${NEO4J_PASSWORD:-devpassword}"

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
