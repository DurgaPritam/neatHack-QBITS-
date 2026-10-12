#!/usr/bin/env bash
# Build on this Mac, copy to the server, restart with Docker Compose. Run from anywhere:
#   scripts/deploy.sh                 # tests + build + copy + up
#   SKIP_TESTS=1 scripts/deploy.sh    # skip the backend test suite
#
# Secrets: backend/.env (API keys) is merged with backend/.env.production (prod-only
# settings: LLM_MODE, ADMIN_TOKEN, CORS, URLs, NEATLOGS_ENV). Both are gitignored. The merged
# file is copied to the server with scp and never printed.
set -euo pipefail

HOST=${DEPLOY_HOST:-ubuntu@3.82.224.157}
KEY=${DEPLOY_KEY:-$HOME/prejudge.pem}
DOMAIN=${DEPLOY_DOMAIN:-3-82-224-157.sslip.io}
REMOTE_DIR=/home/ubuntu/prejudge
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SSH=(ssh -i "$KEY" -o ConnectTimeout=15 "$HOST")
RSYNC_SSH="ssh -i $KEY -o ConnectTimeout=15"

step() { printf '\n== %s\n' "$*"; }

[ -f "$ROOT/backend/.env" ] || { echo "backend/.env is missing"; exit 1; }

# -- production settings (created once; ADMIN_TOKEN is generated here and stays the same)
PROD="$ROOT/backend/.env.production"
if [ ! -f "$PROD" ]; then
  step "creating backend/.env.production (new random ADMIN_TOKEN)"
  (umask 077; cat >"$PROD" <<EOF
# Production overrides, merged over backend/.env by scripts/deploy.sh. Never commit.
LLM_MODE=live
ADMIN_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
CORS_ORIGINS=https://$DOMAIN
PUBLIC_API_URL=https://$DOMAIN
FRONTEND_URL=https://$DOMAIN
NEATLOGS_ENV=prod
SITE_DOMAIN=$DOMAIN
EOF
  )
fi

if [ "${SKIP_TESTS:-0}" != "1" ]; then
  step "backend tests"
  (cd "$ROOT/backend" && .venv/bin/python -m pytest -q 2>&1 | tail -1)
fi

step "building the frontend (on this Mac)"
(cd "$ROOT/frontend" && npm run build --silent >/dev/null && ls dist/index.html >/dev/null)

step "merging env files"
MERGED=$(mktemp)
trap 'rm -f "$MERGED"' EXIT
chmod 600 "$MERGED"
# keys set in .env.production win; comments and blank lines dropped
python3 - "$ROOT/backend/.env" "$PROD" "$MERGED" <<'PY'
import sys
def read(p):
    out = {}
    for line in open(p):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out
env = {**read(sys.argv[1]), **read(sys.argv[2])}
with open(sys.argv[3], "w") as f:
    f.writelines(f"{k}={v}\n" for k, v in env.items())
print(f"{len(env)} settings")
PY

step "copying to $HOST:$REMOTE_DIR"
"${SSH[@]}" "mkdir -p $REMOTE_DIR/site $REMOTE_DIR/backups $REMOTE_DIR/backend"
rsync -az --delete -e "$RSYNC_SSH" \
  --exclude '__pycache__' --exclude '.env*' --exclude '*.db' \
  "$ROOT/backend/app" "$ROOT/backend/fixtures" "$ROOT/backend/requirements.txt" \
  "$ROOT/backend/Dockerfile" "$ROOT/backend/.dockerignore" "$HOST:$REMOTE_DIR/backend/"
CADDY_BEFORE=$("${SSH[@]}" "sha256sum $REMOTE_DIR/Caddyfile 2>/dev/null | cut -c1-64" || true)
rsync -az -e "$RSYNC_SSH" "$ROOT/deploy/docker-compose.yml" "$ROOT/deploy/Caddyfile" "$HOST:$REMOTE_DIR/"
# --delay-updates: new hashed assets land before index.html points at them
rsync -az --delete --delay-updates -e "$RSYNC_SSH" "$ROOT/frontend/dist/" "$HOST:$REMOTE_DIR/site/"
scp -q -i "$KEY" "$MERGED" "$HOST:$REMOTE_DIR/.env"
"${SSH[@]}" "chmod 600 $REMOTE_DIR/.env"

step "docker compose up -d --build"
"${SSH[@]}" "cd $REMOTE_DIR && sudo docker compose up -d --build --remove-orphans 2>&1 | grep -v '^ *#' | tail -15 \
  && sudo docker image prune -f >/dev/null && sudo docker compose ps --format 'table {{.Service}}\t{{.Status}}'"

# rsync swaps the Caddyfile for a new file, but a single-file bind mount keeps showing the old one:
# restart Caddy when the routing changed (about a second of downtime).
if [ "$CADDY_BEFORE" != "$(shasum -a 256 "$ROOT/deploy/Caddyfile" | cut -c1-64)" ]; then
  step "Caddyfile changed: restarting caddy"
  "${SSH[@]}" "cd $REMOTE_DIR && sudo docker compose restart caddy 2>&1 | tail -1"
fi

step "waiting for https://$DOMAIN/api/health"
for _ in $(seq 1 40); do
  if curl -fsS --max-time 5 "https://$DOMAIN/api/health" 2>/dev/null; then echo; echo "deployed: https://$DOMAIN"; exit 0; fi
  sleep 3
done
echo "health check didn't pass; see DEPLOY.md (logs: sudo docker compose logs --tail 100)"; exit 1
