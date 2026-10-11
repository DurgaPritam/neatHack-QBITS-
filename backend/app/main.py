"""FastAPI routes.

POST /api/audits {repo_url}          -> quick phase only: {id, status, cached}
POST /api/audits/{id}/deep           -> queue the deep phase: {queue: {position, estimated_wait_s}}
GET  /api/audits/{id}                -> status, phases, queue position + ETA, steps, result
POST /api/audits/{id}/feedback       -> "this verdict is wrong" for a check or claim
GET  /api/stats                      -> public counter + budget state (normal | busy | cooling)
GET  /api/examples                   -> saved example audits for the home page
GET  /api/audits/{id}/card.png       -> 1200x630 roast card (link previews)
GET  /r/{id}                         -> share page: Open Graph/Twitter meta, redirects to /a/{id}
POST /api/audits/{id}/removal        -> hide an audit from public view (admin can restore)
POST /api/events {name}              -> count a card download or Share-on-X click (no cookies)
GET  /api/admin/feedback?format=csv  -> feedback export        (X-Admin-Token)
GET  /api/admin/metrics              -> per-day counts         (X-Admin-Token)
GET  /api/admin/removals             -> hidden audits          (X-Admin-Token)
POST /api/admin/audits/{id}/restore  -> undo a removal         (X-Admin-Token)

Abuse protection (app.limits): per-IP limits on new audits and deep checks, a max deep-queue
length, and a per-repo cooldown that hands back the recent audit of the same commit instead of
running a new one.

Status: queued -> quick_ready -> complete | failed. Deep phase: available -> queued ->
(waiting_budget) -> running -> done | failed | skipped.
Requests with a valid X-Admin-Token header may use the reserved share of the LLM budget.
"""
import csv
import hmac
import io
import json
import html
import uuid
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import budget, config, db, limits, replay
from app.card import render_card
from app.jobs import AuditQueues
from app.llm import POOL, configured_models
from app.tools.github import GitHubClient, GitHubError, parse_repo_url
from app.tracing import flush, init_tracing

queues = AuditQueues()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_tracing()
    db.connect()
    db.mark_interrupted()
    db.seed_examples()
    budget.attach(POOL)
    queues.start()
    yield
    await queues.stop()
    flush()


app = FastAPI(title="PreJudge", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in config.env("CORS_ORIGINS", "http://localhost:5173").split(",")],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Admin-Token"],
)

NOINDEX = {"X-Robots-Tag": "noindex, nofollow"}


@app.middleware("http")
async def noindex_results(request: Request, call_next):
    """Audit results, cards and share pages stay out of search engines."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith(("/r/", "/api/audits/", "/api/admin/")):
        response.headers.update(NOINDEX)
    return response


class AuditRequest(BaseModel):
    repo_url: str = Field(min_length=3, max_length=300)
    run_kind: Literal["real", "test"] = "real"


class RemovalRequest(BaseModel):
    reason: str = Field(default="", max_length=300)


class EventRequest(BaseModel):
    name: Literal["card_download", "share_x"]


class FeedbackRequest(BaseModel):
    check_id: str = Field(min_length=1, max_length=100)
    is_wrong: bool = True
    note: str = Field(default="", max_length=500)


def is_admin(token: str | None) -> bool:
    expected = config.env("ADMIN_TOKEN")
    return bool(expected and token and hmac.compare_digest(token, expected))


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if not is_admin(x_admin_token):
        raise HTTPException(401, "admin token required")


def client_ip(request: Request) -> str:
    """uvicorn --proxy-headers puts the real client address here when behind Caddy."""
    return request.client.host if request.client else "unknown"


def too_many(window: limits.SlidingWindow, key: str, message: str) -> None:
    wait = window.hit(key)
    if wait:
        raise HTTPException(429, f"{message} Try again in {limits.wait_text(wait)}.",
                            headers={"Retry-After": str(int(wait))})


async def resolve_head_sha(repo_url: str) -> str | None:
    """Latest commit SHA for the cache key; None if GitHub can't tell us (the audit will say why)."""
    try:
        async with GitHubClient() as gh:
            return await gh.get_head_sha(parse_repo_url(repo_url))
    except GitHubError:
        return None


def _get(audit_id: str, admin: bool = False) -> dict:
    row = db.get(audit_id)
    if row is None:
        raise HTTPException(404, "audit not found")
    if row.get("hidden") and not admin:
        raise HTTPException(410, "This audit was removed at the owner's request.")
    return row


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "llm_mode": replay.mode()}


@app.post("/api/audits", status_code=202, responses={400: {"description": "Not a GitHub repo URL"},
                                                      429: {"description": "Too many audits from this IP"}})
async def create_audit(req: AuditRequest, request: Request, x_admin_token: str | None = Header(default=None)) -> dict:
    try:
        ref = parse_repo_url(req.repo_url)
    except GitHubError as exc:
        raise HTTPException(400, str(exc)) from exc
    repo_key = ref.full_name.lower()
    admin = is_admin(x_admin_token)

    head_sha = await resolve_head_sha(req.repo_url)
    audit_id = uuid.uuid4().hex[:12]

    if head_sha:
        cached = db.find_cached(repo_key, head_sha)
        if cached:
            result = {**cached["result"], "audit_id": audit_id, "cached_from": cached["id"]}
            deep = "done" if cached["status"] == "complete" else "available"
            db.create(audit_id, req.repo_url, repo_key, head_sha, req.run_kind, status=cached["status"],
                      phase_quick="done", phase_deep=deep, cached_from=cached["id"],
                      steps=cached["steps"], result=result)
            return {"id": audit_id, "status": cached["status"], "cached": True}
        running = db.find_in_progress(repo_key, head_sha)
        if running:  # same commit already being audited: follow that one
            return {"id": running["id"], "status": running["status"], "cached": False, "deduplicated": True}

    if not admin and limits.REPO_COOLDOWN_S > 0:
        recent = db.recent_for_repo(repo_key, limits.REPO_COOLDOWN_S)
        # Per-repo cooldown: same commit (or unknown) -> hand back the recent audit, no new work.
        # A new push always gets a fresh audit (the per-IP limit still applies).
        recent_sha = recent and (recent.get("commit_sha") or recent.get("head_sha"))  # older rows: head_sha only
        if recent and (head_sha is None or recent_sha in (None, head_sha)):
            return {"id": recent["id"], "status": recent["status"], "cached": True, "cooldown": True}

    if not admin:
        too_many(limits.AUDITS, client_ip(request),
                 f"Easy there: {limits.AUDITS.limit} new audits per 10 minutes per person.")
    db.create(audit_id, req.repo_url, repo_key, head_sha, req.run_kind)
    queue = await queues.submit(audit_id, req.repo_url, req.run_kind, use_reserve=admin)
    return {"id": audit_id, "status": "queued", "cached": False, "queue": queue}


@app.post("/api/audits/{audit_id}/deep", status_code=202,
          responses={404: {"description": "Audit not found"}, 409: {"description": "Deep check not possible"},
                     429: {"description": "Too many deep checks from this IP"},
                     503: {"description": "Deep queue full"}})
def request_deep(audit_id: str, request: Request, x_admin_token: str | None = Header(default=None)) -> dict:
    admin = is_admin(x_admin_token)
    row = _get(audit_id, admin)
    if row["status"] == "complete":
        return {"id": audit_id, "status": "complete", "queue": None}
    if row["status"] != "quick_ready":
        raise HTTPException(409, f"quick result isn't ready (status: {row['status']})")
    if row["phase_deep"] == "skipped":
        raise HTTPException(409, "nothing to verify: the repo couldn't be read")
    if audit_id not in queues.deep and not admin:  # asking again for a queued audit is free
        if queues.deep.length() >= limits.DEEP_QUEUE_MAX:
            raise HTTPException(503, f"The deep-check queue is full ({queues.deep.length()} waiting). Your quick "
                                     "result is saved; try the deep check again in a few minutes.",
                                headers={"Retry-After": "300"})
        too_many(limits.DEEP, client_ip(request),
                 f"You've used your {limits.DEEP.limit} deep checks for this hour.")
    if audit_id not in queues.deep:
        db.bump("deep_requested")
    queue = queues.request_deep(audit_id, use_reserve=admin)
    return {"id": audit_id, "status": row["status"], "phase_deep": "queued", "queue": queue}


@app.get("/api/audits/{audit_id}", responses={404: {"description": "Audit not found"}})
def get_audit(audit_id: str, x_admin_token: str | None = Header(default=None)) -> dict:
    row = _get(audit_id, is_admin(x_admin_token))
    return {
        "hidden": bool(row.get("hidden")),
        "id": row["id"],
        "repo_url": row["repo_url"],
        "status": row["status"],
        "phases": {"quick": row["phase_quick"], "deep": row["phase_deep"]},
        "queue": queues.position(audit_id),
        "cached": row["cached_from"] is not None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "steps": row["steps"],
        "result": row["result"],
        "error": row["error"],
    }


@app.post("/api/audits/{audit_id}/feedback", status_code=201, responses={404: {"description": "Audit not found"}})
def feedback(audit_id: str, req: FeedbackRequest) -> dict:
    _get(audit_id)
    db.add_feedback(audit_id, req.check_id, req.is_wrong, req.note)
    return {"ok": True}


@app.post("/api/audits/{audit_id}/removal", responses={404: {"description": "Audit not found"},
                                                       429: {"description": "Too many removal requests"}})
def request_removal(audit_id: str, request: Request, req: RemovalRequest | None = None) -> dict:
    row = db.get(audit_id)
    if row is None:
        raise HTTPException(404, "audit not found")
    if not row.get("hidden"):
        too_many(limits.REMOVALS, client_ip(request), "Too many removal requests.")
        db.set_hidden(audit_id, True, (req.reason if req else "") or "removal requested")
        db.bump("removals")
    return {"ok": True, "hidden": True}


@app.post("/api/events", status_code=204)
def count_event(req: EventRequest, request: Request) -> Response:
    """A bare per-day counter: no cookies, no IPs stored (the IP only feeds the in-memory limiter)."""
    if not limits.EVENTS.hit(client_ip(request)):
        db.bump(req.name)
    return Response(status_code=204)


# ---------------------------------------------------------------- admin

@app.get("/api/admin/feedback", dependencies=[Depends(require_admin)])
def admin_feedback(format: Literal["json", "csv"] = "json"):
    rows = db.all_feedback()
    if format == "json":
        return rows
    buf = io.StringIO()
    fields = ["id", "audit_id", "repo_url", "check_id", "is_wrong", "note", "created_at"]
    w = csv.DictWriter(buf, fieldnames=fields)
    w.writeheader()
    for r in rows:  # neutralise spreadsheet formulas in user-written notes
        w.writerow({k: ("'" + v if isinstance(v, str) and v[:1] in "=+-@" else v) for k, v in r.items()})
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="prejudge-feedback.csv"'})


@app.get("/api/admin/metrics", dependencies=[Depends(require_admin)])
def admin_metrics() -> dict:
    return {**db.metrics(), "deep_queue": queues.deep.length(), "llm_mode": replay.mode()}


@app.get("/api/admin/removals", dependencies=[Depends(require_admin)])
def admin_removals() -> list[dict]:
    return db.hidden_audits()


@app.post("/api/admin/audits/{audit_id}/restore", dependencies=[Depends(require_admin)],
          responses={404: {"description": "Audit not found"}})
def admin_restore(audit_id: str) -> dict:
    if db.get(audit_id) is None:
        raise HTTPException(404, "audit not found")
    db.set_hidden(audit_id, False)
    return {"ok": True, "hidden": False}


def budget_state() -> str:
    """normal | busy (deep queue long) | cooling (public LLM budget used up: templates in use)."""
    if replay.mode() != "replay" and not POOL.budget(configured_models(), est=3000)["public_available"]:
        return "cooling"
    return "busy" if queues.busy() else "normal"


@app.get("/api/stats")
def stats() -> dict:
    return {**db.stats(), "budget_state": budget_state(), "deep_queue": queues.deep.length(),
            "deep_wait_s": round(queues.deep.avg_s * queues.deep.length()), "llm_mode": replay.mode()}


@app.get("/api/examples")
def examples() -> list[dict]:
    out = []
    for row in db.examples():
        r = row["result"] or {}
        out.append({"id": row["id"], "repo": (r.get("repo") or {}).get("full_name") or row["repo_url"],
                    "score": (r.get("score") or {}).get("score"), "roast": (r.get("verdict") or {}).get("roast"),
                    "style": (r.get("verdict") or {}).get("style"), "status": row["status"]})
    return out


def _site_urls() -> tuple[str, str]:
    """(api base used in og:image, frontend base for /a/{id}); absolute URLs for crawlers."""
    api = config.env("PUBLIC_API_URL", "http://localhost:8000").rstrip("/")
    front = config.env("FRONTEND_URL", "http://localhost:5173").rstrip("/")
    return api, front


def _card_bits(row: dict) -> dict:
    r = row["result"] or {}
    verdict = r.get("verdict") or {}
    repo = (r.get("repo") or {}).get("full_name") or row["repo_url"]
    roast = verdict.get("roast") or "Still in the oven: check back in a few seconds."
    return {"repo": repo, "score": (r.get("score") or {}).get("score"), "roast": roast,
            "source": verdict.get("source", "llm")}


@app.get("/api/audits/{audit_id}/card.png", responses={404: {"description": "Audit not found"}})
def card_png(audit_id: str) -> Response:
    row = _get(audit_id)
    db.bump("card_png")
    site = _site_urls()[1].split("://")[-1]
    png = render_card(site=site, **_card_bits(row))
    cache = "public, max-age=300" if row["status"] == "complete" else "no-store"
    return Response(png, media_type="image/png", headers={"Cache-Control": cache})


@app.get("/r/{audit_id}", response_class=HTMLResponse, responses={404: {"description": "Audit not found"}})
def share_page(audit_id: str) -> HTMLResponse:
    api, front = _site_urls()
    target = f"{front}/a/{audit_id}"
    row = db.get(audit_id)
    if row is None or row.get("hidden"):
        # People follow share links: send them to the app's friendly "no such / removed" page.
        code = 404 if row is None else 410
        t = html.escape(target)
        return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="robots" content="noindex, nofollow"><title>PreJudge</title>
<meta http-equiv="refresh" content="0; url={t}"></head>
<body><p><a href="{t}">Continue to PreJudge</a></p></body></html>""", status_code=code)
    bits = _card_bits(row)
    score = "?" if bits["score"] is None else bits["score"]
    title = html.escape(f"{bits['repo']} scored {score}/100 on PreJudge")
    desc = html.escape(bits["roast"][:280])          # roast quotes repo text: always escaped
    image = html.escape(f"{api}/api/audits/{audit_id}/card.png")
    t = html.escape(target)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{title}</title>
<meta name="robots" content="noindex, nofollow">
<meta name="description" content="{desc}">
<meta property="og:type" content="website">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:image" content="{image}">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta property="og:url" content="{t}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="{image}">
<meta http-equiv="refresh" content="0; url={t}">
</head><body><p>Redirecting to <a href="{t}">the full roast</a>…</p>
<script>location.replace({json.dumps(target)});</script></body></html>"""
    return HTMLResponse(page)
