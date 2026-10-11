# Deploying PreJudge

Production: **https://3-82-224-157.sslip.io**. One EC2 t3.small (Ubuntu 26.04, us-east-1,
`3.82.224.157`) runs three containers with Docker Compose:

| service   | what it does |
|-----------|--------------|
| `backend` | FastAPI + uvicorn (one worker, because the audit queues live in memory), healthcheck on `/api/health`, `restart: unless-stopped` |
| `caddy`   | automatic HTTPS (Let's Encrypt for the sslip.io name), serves the built React app, proxies `/api/*` and `/r/*` to the backend |
| `backup`  | daily SQLite copy to `~/prejudge/backups/prejudge-YYYY-MM-DD.db` (keeps 7) |

SQLite lives on the named volume `prejudge_prejudge-data` (`/data/prejudge.db` in the container).
The frontend is built on the Mac, never on the server.

## Files

| file | where it ends up |
|------|------------------|
| `deploy/docker-compose.yml`, `deploy/Caddyfile` | `~/prejudge/` |
| `backend/{app,fixtures,requirements.txt,Dockerfile}` | `~/prejudge/backend/` (image built on the server) |
| `frontend/dist/` (built locally) | `~/prejudge/site/` |
| `backend/.env` + `backend/.env.production`, merged | `~/prejudge/.env` (mode 600, copied with scp) |

`backend/.env.production` holds the production-only settings and is gitignored like `.env`.
`scripts/deploy.sh` creates it on the first run with a fresh random `ADMIN_TOKEN`:

```
LLM_MODE=live
ADMIN_TOKEN=<random>
CORS_ORIGINS=https://3-82-224-157.sslip.io
PUBLIC_API_URL=https://3-82-224-157.sslip.io
FRONTEND_URL=https://3-82-224-157.sslip.io
NEATLOGS_ENV=prod          # neatlogs traces are tagged "prod"
```

Keys in `.env.production` override the same keys in `.env`. To rotate an API key, edit
`backend/.env` and deploy again. Never commit either file and never paste them into chat.

## First-time server setup (already done)

```bash
# from the repo root on the Mac: 2 GB swap file, Docker Engine + Compose plugin, ~/prejudge
ssh -i ~/prejudge.pem ubuntu@3.82.224.157 'bash -s' < scripts/server-setup.sh
```

The security group must allow inbound TCP 22, 80 and 443 (80 is needed for the certificate).

## Deploy

```bash
scripts/deploy.sh                 # backend tests, frontend build, copy, docker compose up -d --build
SKIP_TESTS=1 scripts/deploy.sh    # same, without the test run
```

The script waits until `https://3-82-224-157.sslip.io/api/health` answers, then prints `deployed`.
Overrides: `DEPLOY_HOST`, `DEPLOY_KEY`, `DEPLOY_DOMAIN`.

## Day-to-day

```bash
ssh -i ~/prejudge.pem ubuntu@3.82.224.157
cd ~/prejudge

sudo docker compose ps                         # status + health
sudo docker compose logs -f --tail 100 backend # follow backend logs (also: caddy, backup)
sudo docker compose logs --since 1h caddy      # access log of the last hour
sudo docker compose restart backend            # restart one service
sudo docker compose up -d                      # start everything (after a reboot it starts by itself)
sudo docker compose down                       # stop everything (volumes and data stay)
sudo docker stats --no-stream                  # memory per container
free -m                                        # RAM + swap
```

A restart marks audits that were in flight as failed or "ask again". It doesn't lose any data.

## Backups and restore

```bash
ls -la ~/prejudge/backups/                                          # daily copies
sudo docker compose run --rm backup python -m app.backup --once     # take one now
scp -i ~/prejudge.pem ubuntu@3.82.224.157:prejudge/backups/prejudge-2026-10-11.db .   # pull to the Mac
```

Restore a copy (stops the backend briefly):

```bash
cd ~/prejudge
sudo docker compose stop backend
sudo docker run --rm -v prejudge_prejudge-data:/data -v "$PWD/backups:/b" alpine \
  sh -c 'cp /b/prejudge-2026-10-11.db /data/prejudge.db && chown 1000:1000 /data/prejudge.db && rm -f /data/prejudge.db-*'
sudo docker compose start backend
```

## Admin endpoints

Send the token from `backend/.env.production` in the `X-Admin-Token` header. Read it into a
shell variable, so it never shows up on screen or in your shell history:

```bash
TOKEN=$(grep '^ADMIN_TOKEN=' backend/.env.production | cut -d= -f2-)
B=https://3-82-224-157.sslip.io
curl -s -H "X-Admin-Token: $TOKEN" $B/api/admin/metrics                    # per-day counts
curl -s -H "X-Admin-Token: $TOKEN" "$B/api/admin/feedback?format=csv" -o feedback.csv
curl -s -H "X-Admin-Token: $TOKEN" $B/api/admin/removals                   # hidden audits
curl -s -X POST -H "X-Admin-Token: $TOKEN" $B/api/admin/audits/<id>/restore
```

Requests with the admin token skip the per-IP limits and may use the reserved LLM budget.

## Abuse limits (change them in `.env.production`, then deploy)

| setting | default | effect |
|---------|---------|--------|
| `RATE_AUDITS_PER_10MIN` | 5 | new audits per IP (cooldown and cache hits don't count) |
| `RATE_DEEP_PER_HOUR` | 3 | deep checks per IP |
| `DEEP_QUEUE_MAX` | 10 | beyond this the user sees "queue full, try again in a few minutes" |
| `REPO_COOLDOWN_S` | 600 | the same repo and commit within 10 min gets the recent audit back (a new push always gets a fresh audit) |

## Troubleshooting

- **Site doesn't load or the certificate fails:** `sudo docker compose logs caddy | grep -i -E "error|acme"`.
  Check that ports 80 and 443 are open in the security group.
- **"backend is unhealthy":** `sudo docker compose logs --tail 200 backend`. Usually a missing
  or broken `.env` value. Fix `backend/.env` locally and run `scripts/deploy.sh` again.
- **Out of memory:** check `free -m` (swap should show 2 GB) and `sudo docker stats --no-stream`.
  The backend is capped at 1 GB.
- **Roasts are templates ("quick facts mode"):** the Groq daily budget ran out.
  `/api/stats` shows `budget_state: cooling`. It recovers by itself.
