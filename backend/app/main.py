"""FastAPI routes.

POST /api/audits {repo_url}  -> {id, status, cached}
GET  /api/audits/{id}        -> status, step log so far, result
GET  /api/stats              -> total audits (public counter)
"""
import uuid
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import db
from app.jobs import AuditQueue
from app.tools.github import GitHubClient, GitHubError, parse_repo_url
from app.tracing import flush, init_tracing

queue = AuditQueue()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_tracing()
    db.connect()
    queue.start()
    yield
    await queue.stop()
    flush()


app = FastAPI(title="PreJudge", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class AuditRequest(BaseModel):
    repo_url: str = Field(min_length=3, max_length=300)
    run_kind: Literal["real", "test"] = "real"


async def resolve_head_sha(repo_url: str) -> str | None:
    """Latest commit SHA for the cache key; None if GitHub can't tell us (the audit will say why)."""
    try:
        async with GitHubClient() as gh:
            return await gh.get_head_sha(parse_repo_url(repo_url))
    except GitHubError:
        return None


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/audits", status_code=202, responses={400: {"description": "Not a GitHub repo URL"}})
async def create_audit(req: AuditRequest) -> dict:
    try:
        ref = parse_repo_url(req.repo_url)
    except GitHubError as exc:
        raise HTTPException(400, str(exc)) from exc
    repo_key = ref.full_name.lower()
    head_sha = await resolve_head_sha(req.repo_url)
    audit_id = uuid.uuid4().hex[:12]

    cached = db.find_cached(repo_key, head_sha) if head_sha else None
    if cached:
        result = {**cached["result"], "audit_id": audit_id, "cached_from": cached["id"]}
        db.create(audit_id, req.repo_url, repo_key, head_sha, req.run_kind, status="done",
                  cached_from=cached["id"], steps=cached["steps"], result=result)
        return {"id": audit_id, "status": "done", "cached": True}

    db.create(audit_id, req.repo_url, repo_key, head_sha, req.run_kind)
    position = await queue.submit(audit_id, req.repo_url, req.run_kind)
    return {"id": audit_id, "status": "queued", "cached": False, "queue_position": position}


@app.get("/api/audits/{audit_id}", responses={404: {"description": "Audit not found"}})
def get_audit(audit_id: str) -> dict:
    row = db.get(audit_id)
    if row is None:
        raise HTTPException(404, "audit not found")
    return {
        "id": row["id"],
        "repo_url": row["repo_url"],
        "status": row["status"],
        "cached": row["cached_from"] is not None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "steps": row["steps"],
        "result": row["result"],
        "error": row["error"],
    }


@app.get("/api/stats")
def stats() -> dict:
    return db.stats()
