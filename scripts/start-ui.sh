#!/usr/bin/env bash
#
# Start the COBOL-modernizer cockpit (Next.js UI) with ONE command.
#
# Installs web dependencies on first run, then runs the dev server on :3000.
# The cockpit proxies /api/* → http://localhost:8000, so start the backend
# first with scripts/start-backend.sh.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/web"

command -v npm >/dev/null || { echo "✗ npm not found — install Node.js 18+ and retry"; exit 1; }

if [ ! -d node_modules ]; then
  echo "→ installing web dependencies (npm install)…"
  npm install
fi

echo "→ cockpit → http://localhost:3000   (proxies /api → http://localhost:8000)"
exec npm run dev
