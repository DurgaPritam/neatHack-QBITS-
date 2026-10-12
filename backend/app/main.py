"""FastAPI routes.

POST /api/audits {repo_url}          -> quick phase only: {id, status, cached}
POST /api/audits/{id}/deep           -> queue the deep phase: {queue: {position, estimated_wait_s}}
GET  /api/audits/{id}                -> status, phases, queue position + ETA, steps, result
POST /api/audits/{id}/feedback       -> "this verdict is wrong" for a check or claim
GET  /api/stats                      -> public counter + budget state (normal | busy | cooling)
GET  /api/examples                   -> saved example audits for the home page
GET  /api/showcase                   -> 'Fresh off the grill': opted-in roasts, topped up with examples
POST /api/audits/{id}/showcase       -> {show} opt in/out of the homepage feed (default off)
GET  /api/audits/{id}/card.png       -> 1200x630 roast card (link previews)
GET  /api/audits/{id}/kit            -> submission post, Evidence section, badge Markdown
GET  /badge/{owner}/{repo}.svg       -> README badge with the latest score
GET  /api/audits/{id}/demo-script    -> 3-minute demo script (FEATURE_DEMO_SCRIPT)
GET  /api/audits/{id}/judge-panel    -> three generic judge personas (FEATURE_JUDGE_PANEL)
GET  /api/audits/{id}/ari-prompt     -> ready-to-paste cfo.ai (Ari) prompt (FEATURE_ARI_PROMPT)
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
import re
import html
import uuid
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import ari, budget, config, costs, db, extras, history, integrity, kit, limits, replay, sponsors, transparency
from app.card import render_card
from app.jobs import DEEP_EST_TOKENS, AuditQueues, cacheable
from app.llm import LLM, POOL, configured_models
from app.steps import StepLog
from app.public import public_steps
from app.tools.github import GitHubClient, GitHubError, parse_repo_url
from app.tools.rubric import CHECKS_VERSION
from app.tracing import flush, init_tracing

queues = AuditQueues()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_tracing()
    db.connect()
    db.mark_interrupted()
    db.seed_examples()
    history.backfill()
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
    if path.startswith(("/r/", "/api/audits/", "/api/admin/", "/admin")):
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


def too_many(window: limits.SlidingWindow, key: str, message: str, kind: str = "rate",
             repo: str | None = None) -> None:
    wait = window.hit(key)
    if wait:
        limits.HITS.add(kind, ip=key, repo=repo)
        db.bump(f"limit:{kind}")
        raise HTTPException(429, f"{message} Try again in {limits.wait_text(wait)}.",
                            headers={"Retry-After": str(int(wait))})


def limit_reached(kind: str, message: str, ip: str, repo: str | None, status: int = 429,
                  retry_after: int = 3600) -> HTTPException:
    """A daily or queue limit: recorded for the admin page, explained to the user."""
    limits.HITS.add(kind, ip=ip, repo=repo)
    db.bump(f"limit:{kind}")
    return HTTPException(status, message, headers={"Retry-After": str(retry_after)})


def _tokens(result: dict | None) -> int:
    return int(((result or {}).get("usage") or {}).get("total_tokens") or 0)


def reuse_result(prior: dict, audit_id: str, deep: bool) -> dict:
    """A stored result handed out again for the same commit: no LLM calls, tokens saved counted."""
    saved = _tokens(prior["result"])
    db.bump("reused_deep" if deep else "reused_audits")
    db.bump("tokens_saved", saved)
    result = {**prior["result"], "audit_id": audit_id, "cached_from": prior["id"],
              "reuse": {"from": prior["id"], "checked_at": prior["created_at"], "tokens_saved": saved,
                        "deep": deep}}
    result.pop("progress", None)  # no new commits: nothing changed since that check
    return result


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
        # Same commit + same check logic = same result, however long ago: no LLM calls.
        cached = db.find_reusable(repo_key, head_sha, CHECKS_VERSION)
        if cached and not cacheable(cached["result"] or {}) and public_budget_ok():
            cached = None  # a fact-only (template) verdict: write a real one while budget allows
        if cached:
            result = reuse_result(cached, audit_id, deep=False)
            deep = "done" if cached["status"] == "complete" else "available"
            db.create(audit_id, req.repo_url, repo_key, head_sha, req.run_kind, status=cached["status"],
                      phase_quick="done", phase_deep=deep, cached_from=cached["id"],
                      steps=cached["steps"], result=result)
            return {"id": audit_id, "status": cached["status"], "cached": True, "reuse": result["reuse"]}
        running = db.find_in_progress(repo_key, head_sha)
        if running:  # same commit already being audited: follow that one
            return {"id": running["id"], "status": running["status"], "cached": False, "deduplicated": True}

    if not admin and limits.REPO_COOLDOWN_S > 0:
        recent = db.recent_for_repo(repo_key, limits.REPO_COOLDOWN_S)
        # Per-repo cooldown: same commit (or unknown) -> hand back the recent audit, no new work.
        # A new push always gets a fresh audit (the per-IP limit still applies).
        recent_sha = recent and (recent.get("commit_sha") or recent.get("head_sha"))  # older rows: head_sha only
        # still running (so it's on the current code), or finished with the current check logic
        current = recent and (recent["status"] == "queued"
                              or (recent["result"] or {}).get("checks_version") == CHECKS_VERSION)
        if current and (head_sha is None or recent_sha in (None, head_sha)):
            return {"id": recent["id"], "status": recent["status"], "cached": True, "cooldown": True}

    if not admin:
        too_many(limits.AUDITS, client_ip(request), limits.MESSAGES["audits_ip"].format(n=limits.AUDITS.limit),
                 kind="audits_ip", repo=repo_key)
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
    repo_key, sha = row.get("repo_key"), row.get("commit_sha")
    if audit_id not in queues.deep and repo_key and sha:
        # No new commits since this repo's last deep check (same check logic): hand that one back.
        prior = db.find_deep_result(repo_key, sha, CHECKS_VERSION)
        if prior and prior["id"] != audit_id:
            result = reuse_result(prior, audit_id, deep=True)
            db.update(audit_id, status="complete", phase_deep="done", result=result, steps=prior["steps"])
            return {"id": audit_id, "status": "complete", "queue": None, "reuse": result["reuse"]}
    ip = client_ip(request)
    if audit_id not in queues.deep and not admin:  # asking again for a queued audit is free
        repo_today = db.today_count(f"deep_repo:{repo_key}")
        if repo_today >= limits.DEEP_PER_REPO_DAILY:
            raise limit_reached("deep_repo", limits.MESSAGES["deep_repo"].format(n=repo_today), ip, repo_key)
        if db.today_count("deep_started") >= limits.DEEP_DAILY_CAP:
            raise limit_reached("deep_daily", limits.MESSAGES["deep_daily"], ip, repo_key)
        if replay.mode() != "replay" and not POOL.public_tokens_ok(DEEP_EST_TOKENS):
            raise limit_reached("public_tokens", limits.MESSAGES["public_tokens"], ip, repo_key)
        if queues.deep.length() >= limits.DEEP_QUEUE_MAX:
            raise limit_reached("deep_queue", limits.MESSAGES["deep_queue"].format(n=queues.deep.length()), ip,
                                repo_key, status=503, retry_after=300)
        too_many(limits.DEEP, ip, limits.MESSAGES["deep_ip"].format(n=limits.DEEP.limit), kind="deep_ip",
                 repo=repo_key)
    if audit_id not in queues.deep:
        db.bump("deep_requested")
        db.bump("deep_started")
        db.bump(f"deep_repo:{repo_key}")
    # Repos with commits inside the hackathon window go first.
    priority = 1 if history.is_hackathon_repo(row["result"] or {}) else 0
    queue = queues.request_deep(audit_id, use_reserve=admin, priority=priority)
    return {"id": audit_id, "status": row["status"], "phase_deep": "queued", "queue": queue}


def public_budget_ok() -> bool:
    return replay.mode() == "replay" or POOL.budget(configured_models(), est=3000)["public_available"]


@app.get("/api/audits/{audit_id}", responses={404: {"description": "Audit not found"}})
def get_audit(audit_id: str, x_admin_token: str | None = Header(default=None)) -> dict:
    admin = is_admin(x_admin_token)
    row = _get(audit_id, admin)
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
        "steps": row["steps"] if admin else public_steps(row["steps"]),  # raw errors: admins only
        "result": _public_result(row["result"]),
        "percentiles": _percentiles(row),
        "showcase": bool(row.get("showcase")),
        "features": {"demo_script": extras.enabled("demo_script"), "judge_panel": extras.enabled("judge_panel"),
                     "ari_prompt": extras.enabled("ari_prompt")},
        "sponsors": _sponsors(row),
        "glass_box": _glass_box(row),
        "error": row["error"],
    }


def _public_result(result: dict | None) -> dict | None:
    """The README fingerprint is for the admin near-duplicate list only; integrity hides behind its flag."""
    if not result or "integrity" not in result:
        return result
    if not integrity.enabled():
        return {k: v for k, v in result.items() if k != "integrity"}
    return {**result, "integrity": {k: v for k, v in result["integrity"].items() if k != "fingerprint"}}


def _sponsors(row: dict) -> list[dict] | None:
    """Sponsor Depth Scorecard (FEATURE_SPONSOR_SCORECARD), computed from the checks on every read."""
    r = row.get("result")
    if not r or not extras.enabled("sponsor_scorecard") or (r.get("score") or {}).get("gated"):
        return None
    try:
        return sponsors.scorecard(r)
    except Exception:
        return None  # a nicety; never break the result page


def _glass_box(row: dict) -> dict | None:
    """'How this verdict was made' (FEATURE_GLASS_BOX): steps, tokens, cost, retries; whitelisted fields only."""
    r = row.get("result")
    if not r or not extras.enabled("glass_box"):
        return None
    try:
        return costs.glass_box(row["steps"], r.get("usage"), r.get("timing_ms"))
    except Exception:
        return None


def _percentiles(row: dict) -> dict | None:
    try:
        return history.percentiles(row.get("repo_key"), row["result"])
    except Exception:
        return None  # a nicety; never break the result page


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


def readme_duplicates(threshold: float = 0.8) -> list[dict]:
    """Admin only: pairs of audited repos whose READMEs are near-duplicates. Never shown publicly."""
    if not integrity.enabled():
        return []
    fps = db.readme_fingerprints()
    out = []
    for i, (a, fa) in enumerate(fps):
        for b, fb in fps[i + 1:]:
            sim = integrity.similarity(fa, fb)
            if sim >= threshold:
                out.append({"a": a, "b": b, "similarity": round(sim, 2)})
    return sorted(out, key=lambda x: -x["similarity"])[:50]


@app.get("/api/admin/overview", dependencies=[Depends(require_admin)])
def admin_overview() -> dict:
    """Everything the /admin page shows, in one call."""
    models = configured_models()
    metrics = db.metrics()
    deep_by_repo = {k.split(":", 1)[1]: v for k, v in db.today_counters("deep_repo:").items()}
    return {
        "readme_duplicates": readme_duplicates(),
        "budget": {**POOL.budget(models), "reserve_pct": POOL.reserve_pct, "snapshot": POOL.snapshot(),
                   "state": budget_state()},
        "deep": {"used_today": db.today_count("deep_started"), "daily_cap": limits.DEEP_DAILY_CAP,
                 "per_repo_cap": limits.DEEP_PER_REPO_DAILY,
                 "by_repo": sorted(({"repo": k, "count": v} for k, v in deep_by_repo.items()),
                                   key=lambda r: -r["count"])},
        "queue": {"quick": queues.quick.length(), "deep": queues.deep.length(),
                  "deep_max": limits.DEEP_QUEUE_MAX, "waiting_budget": queues.deep.waiting_budget},
        "reuse": {"tokens_saved_today": db.today_count("tokens_saved"),
                  "tokens_saved_total": metrics["totals"].get("tokens_saved", 0),
                  "reused_today": db.today_count("reused_audits") + db.today_count("reused_deep")},
        "limits": {**limits.HITS.summary(), "today": db.today_counters("limit:")},
        "projects": db.all_projects(),
        "recent_audits": db.recent_audits(),
        "feedback": db.all_feedback()[-100:][::-1],
        "metrics": metrics,
        "llm_mode": replay.mode(),
    }


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


def _feed_item(row: dict, example: bool) -> dict:
    r = row["result"] or {}
    return {"id": row["id"], "repo": (r.get("repo") or {}).get("full_name") or row["repo_url"],
            "score": (r.get("score") or {}).get("score"), "roast": (r.get("verdict") or {}).get("roast"),
            "style": (r.get("verdict") or {}).get("style"), "status": row["status"], "example": example}


@app.get("/api/examples")
def examples() -> list[dict]:
    return [_feed_item(row, True) for row in db.examples()]


SHOWCASE_MIN, SHOWCASE_MAX = 3, 6


@app.get("/api/transparency")
def transparency_stats(response: Response) -> dict:
    """Live aggregate numbers vs the cfo.ai plan (FEATURE_TRANSPARENCY). Cached 5 minutes; no repo names."""
    if not extras.enabled("transparency"):
        raise HTTPException(404, "transparency is switched off")
    response.headers["Cache-Control"] = "public, max-age=300"
    return transparency.get()


@app.get("/api/showcase")
def showcase() -> list[dict]:
    """'Fresh off the grill': the newest roasts whose teams opted in, topped up with the built-in examples."""
    items = [_feed_item(row, False) for row in db.showcase(SHOWCASE_MAX)]
    for ex in examples():
        if len(items) >= SHOWCASE_MIN:
            break
        items.append(ex)
    return items


class ShowcaseRequest(BaseModel):
    show: bool


@app.post("/api/audits/{audit_id}/showcase", responses={404: {"description": "Audit not found"}})
def set_showcase(audit_id: str, req: ShowcaseRequest, request: Request) -> dict:
    row = _get(audit_id)
    if row.get("is_example"):
        raise HTTPException(400, "built-in examples are always shown")
    too_many(limits.SHOWCASE, client_ip(request), "Too many changes.")
    db.set_showcase(audit_id, req.show)
    return {"ok": True, "showcase": req.show}


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
    delta = (r.get("progress") or {}).get("delta")
    return {"repo": repo, "score": (r.get("score") or {}).get("score"), "roast": roast,
            "source": verdict.get("source", "llm"), "delta": delta if delta and delta > 0 else None}


@app.get("/api/audits/{audit_id}/card.png", responses={404: {"description": "Audit not found"}})
def card_png(audit_id: str) -> Response:
    row = _get(audit_id)
    db.bump("card_png")
    site = _site_urls()[1].split("://")[-1]
    png = render_card(site=site, **_card_bits(row))
    cache = "public, max-age=300" if row["status"] == "complete" else "no-store"
    return Response(png, media_type="image/png", headers={"Cache-Control": cache})


@app.get("/api/audits/{audit_id}/kit", responses={404: {"description": "Audit not found"}})
def submission_kit(audit_id: str) -> dict:
    """Copy-paste helpers: the submission post, a README Evidence section and the score badge."""
    row = _get(audit_id)
    report = row["result"] or {}
    _, front = _site_urls()
    api = config.env("PUBLIC_API_URL", "http://localhost:8000").rstrip("/")
    full = (report.get("repo") or {}).get("full_name") or row["repo_key"] or ""
    result_url = f"{front}/a/{audit_id}"
    badge = f"{api}/badge/{full}.svg"
    return {"post": kit.submission_post(report), "evidence_md": kit.evidence_markdown(report, result_url),
            "badge": {"url": badge, "markdown": f"[![PreJudge score]({badge})]({result_url})"}}


async def _extra(audit_id: str, flag: str, request: Request, x_admin_token: str | None) -> dict:
    """One LLM call per audit version (cached); the template when the budget, the rate limit or replay says no."""
    if not extras.enabled(flag):
        raise HTTPException(404, f"{flag} is switched off")
    row = _get(audit_id)
    report = row["result"]
    if not report:
        raise HTTPException(409, "the audit has no result yet")
    stamp = f"{extras.EXTRAS_VERSION}:{row['updated_at']}"
    if (cached := db.get_extra(audit_id, flag, stamp)):
        return cached
    admin = is_admin(x_admin_token)
    use_llm = replay.mode() != "replay" and (admin or public_budget_ok())
    if use_llm and not admin and limits.EXTRAS.hit(client_ip(request)):
        use_llm = False                      # rate limited: the template, not an error
    llm = LLM(StepLog(), priority="high", use_reserve=admin) if use_llm else None
    makers = {"demo_script": extras.demo_script, "judge_panel": extras.judge_panel, "ari_prompt": ari.ari_prompt}
    body = await makers[flag](report, llm)
    db.bump(f"extra_{flag}_{body['source']}")
    if body["source"] == "llm":
        db.put_extra(audit_id, flag, stamp, body)   # a template from a budget gap is retried next time
    return body


@app.get("/api/audits/{audit_id}/demo-script", responses={404: {"description": "Audit not found or feature off"}})
async def demo_script(audit_id: str, request: Request, x_admin_token: str | None = Header(default=None)) -> dict:
    return await _extra(audit_id, "demo_script", request, x_admin_token)


@app.get("/api/audits/{audit_id}/ari-prompt", responses={404: {"description": "Audit not found or feature off"}})
async def ari_prompt(audit_id: str, request: Request, x_admin_token: str | None = Header(default=None)) -> dict:
    return await _extra(audit_id, "ari_prompt", request, x_admin_token)


@app.get("/api/audits/{audit_id}/judge-panel", responses={404: {"description": "Audit not found or feature off"}})
async def judge_panel(audit_id: str, request: Request, x_admin_token: str | None = Header(default=None)) -> dict:
    return await _extra(audit_id, "judge_panel", request, x_admin_token)


_REPO_PART = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


@app.get("/badge/{owner}/{repo}.svg", responses={200: {"content": {"image/svg+xml": {}}}})
def badge(owner: str, repo: str) -> Response:
    """README badge with the repo's latest score; 'not roasted' if there's none (or it was removed)."""
    if not (_REPO_PART.match(owner) and _REPO_PART.match(repo)):
        raise HTTPException(400, "bad repo name")
    row = db.latest_scored(f"{owner}/{repo}")
    score = ((row or {}).get("result") or {}).get("score", {}).get("score") if row else None
    return Response(kit.badge_svg(score), media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=300", "X-Robots-Tag": "noindex"})


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
