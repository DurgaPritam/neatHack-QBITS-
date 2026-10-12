#!/usr/bin/env bash
# Put the previous deploy back: the backend image, the built site and .env saved by deploy.sh.
#   ./scripts/rollback.sh
set -euo pipefail
HOST=${DEPLOY_HOST:-ubuntu@3.82.224.157}
KEY=${DEPLOY_KEY:-$HOME/prejudge.pem}
REMOTE_DIR=/home/ubuntu/prejudge
DOMAIN=${SITE_DOMAIN:-3-82-224-157.sslip.io}
ssh -i "$KEY" -o ConnectTimeout=15 "$HOST" "cd $REMOTE_DIR && test -d site.previous \
  && sudo docker image inspect prejudge-backend:previous >/dev/null \
  && sudo docker tag prejudge-backend:previous prejudge-backend:latest \
  && rm -rf site.rollback-from && mv site site.rollback-from && cp -a site.previous site \
  && (test -f .env.previous && cp -p .env.previous .env || true) \
  && sudo docker compose up -d --no-build --force-recreate backend 2>&1 | tail -3"
for _ in $(seq 1 30); do
  if curl -fsS --max-time 5 "https://$DOMAIN/api/health"; then echo; echo "rolled back: https://$DOMAIN"; exit 0; fi
  sleep 3
done
echo "health check didn't pass after rollback"; exit 1
