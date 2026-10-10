"""FastAPI routes.

POST /api/audits {repo_url}          -> quick phase only: {id, status, cached}
POST /api/audits/{id}/deep           -> queue the deep phase: {queue: {position, estimated_wait_s}}
GET  /api/audits/{id}                -> status, phases, queue position + ETA, steps, result
POST /api/audits/{id}/feedback       -> "this verdict is wrong" for a check or claim
GET  /api/stats                      -> public counter + budget state (normal | busy | cooling)
GET  /api/examples                   -> saved example audits for the home page

Status: queued -> quick_ready -> complete | failed. Deep phase: available -> queued ->
(waiting_budget) -> running -> done | failed | skipped.
Requests with a valid X-Admin-Token header may use the reserved share of the LLM budget.
"""
import hmac
import uuid
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import budget, config, db, replay
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


class AuditRequest(BaseModel):
    repo_url: str = Field(min_length=3, max_length=300)
    run_kind: Literal["real", "test"] = "real"


class FeedbackRequest(BaseModel):
    check_id: str = Field(min_length=1, max_length=100)
    is_wrong: bool = True
    note: str = Field(default="", max_length=500)


def is_admin(token: str | None) -> bool:
    expected = config.env("ADMIN_TOKEN")
    return bool(expected and token and hmac.compare_digest(token, expected))


async def resolve_head_sha(repo_url: str) -> str | None:
    """Latest commit SHA for the cache key; None if GitHub can't tell us (the audit will say why)."""
    try:
        async with GitHubClient() as gh:
            return await gh.get_head_sha(parse_repo_url(repo_url))
    except GitHubError:
        return None


def _get(audit_id: str) -> dict:
    row = db.get(audit_id)
    if row is None:
        raise HTTPException(404, "audit not found")
    return row


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "llm_mode": replay.mode()}


@app.post("/api/audits", status_code=202, responses={400: {"description": "Not a GitHub repo URL"}})
async def create_audit(req: AuditRequest, x_admin_token: str | None = Header(default=None)) -> dict:
    try:
        ref = parse_repo_url(req.repo_url)
    except GitHubError as exc:
        raise HTTPException(400, str(exc)) from exc
    repo_key = ref.full_name.lower()
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

    db.create(audit_id, req.repo_url, repo_key, head_sha, req.run_kind)
    queue = await queues.submit(audit_id, req.repo_url, req.run_kind, use_reserve=is_admin(x_admin_token))
    return {"id": audit_id, "status": "queued", "cached": False, "queue": queue}


@app.post("/api/audits/{audit_id}/deep", status_code=202,
          responses={404: {"description": "Audit not found"}, 409: {"description": "Deep check not possible"}})
def request_deep(audit_id: str, x_admin_token: str | None = Header(default=None)) -> dict:
    row = _get(audit_id)
    if row["status"] == "complete":
        return {"id": audit_id, "status": "complete", "queue": None}
    if row["status"] != "quick_ready":
        raise HTTPException(409, f"quick result isn't ready (status: {row['status']})")
    if row["phase_deep"] == "skipped":
        raise HTTPException(409, "nothing to verify: the repo couldn't be read")
    queue = queues.request_deep(audit_id, use_reserve=is_admin(x_admin_token))
    return {"id": audit_id, "status": row["status"], "phase_deep": "queued", "queue": queue}


@app.get("/api/audits/{audit_id}", responses={404: {"description": "Audit not found"}})
def get_audit(audit_id: str) -> dict:
    row = _get(audit_id)
    return {
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
