#!/usr/bin/env bash
# End-to-end run with no LLM tokens: backend in LLM_MODE=replay on a fresh SQLite file,
# Vite dev server proxying to it, then Playwright. GitHub calls are live (free).
#   cd frontend && ./e2e/run.sh            (screenshots go to e2e-shots/)
set -euo pipefail
cd "$(dirname "$0")/.."
FRONT=$(pwd)
BACK="$FRONT/../backend"
PORT_API=${PORT_API:-8010}
PORT_WEB=${PORT_WEB:-5173}
TMP=$(mktemp -d)
mkdir -p "${E2E_SHOTS:-e2e-shots}"

cleanup() { kill "$API_PID" "$WEB_PID" 2>/dev/null || true; rm -rf "$TMP"; }
trap cleanup EXIT

for port in "$PORT_API" "$PORT_WEB"; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "port $port is already in use; stop that process or set PORT_API / PORT_WEB"; exit 1
  fi
done

(cd "$BACK" && LLM_MODE=replay NEATLOGS_API_KEY= ADMIN_TOKEN=e2e-admin PREJUDGE_DB="$TMP/e2e.db" \
  PUBLIC_API_URL="http://localhost:$PORT_API" FRONTEND_URL="http://localhost:$PORT_WEB" \
  exec .venv/bin/uvicorn app.main:app --port "$PORT_API" >"$TMP/api.log" 2>&1) &  # exec: the PID is uvicorn
API_PID=$!
VITE_BACKEND="http://localhost:$PORT_API" npx vite --port "$PORT_WEB" --strictPort >"$TMP/web.log" 2>&1 &
WEB_PID=$!

for _ in $(seq 1 30); do
  curl -sf "http://localhost:$PORT_WEB/api/health" | grep -q '"replay"' && break
  sleep 1
done
curl -sf "http://localhost:$PORT_WEB/api/health" | grep -q '"replay"' || { echo "stack didn't start"; cat "$TMP/api.log"; exit 1; }

E2E_BASE_URL="http://localhost:$PORT_WEB" npx playwright test "$@"
