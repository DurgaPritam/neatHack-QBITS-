"""PreJudge MCP server (stdio): audit a hackathon repo from Claude Code, Cursor or any MCP client.

A thin wrapper around PreJudge's public API. It never runs the audited code (PreJudge doesn't
either) and keeps to the API's rate limits: it waits politely between new audits, polls slowly,
and on HTTP 429 tells you when to try again instead of retrying in a loop.

    PREJUDGE_API=https://3-82-224-157.sslip.io python prejudge_mcp.py
"""
import asyncio
import os
import time

import httpx
from mcp.server.fastmcp import FastMCP

API = os.environ.get("PREJUDGE_API", "https://3-82-224-157.sslip.io").rstrip("/")
POLL_S = 3.0                  # the web app polls every 1.5s; an agent can be gentler
QUICK_WAIT_S = 120            # a quick audit usually takes ~15s, more when the queue is busy
DEEP_WAIT_S = 420
MIN_GAP_S = 20                # between new audits from this process (the API allows 5 per 10 minutes)

mcp = FastMCP("prejudge")
_last_audit = 0.0


class ApiError(Exception):
    pass


async def _call(method: str, path: str, **kw) -> dict:
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "prejudge-mcp/0.1"}) as c:
        r = await c.request(method, f"{API}{path}", **kw)
    if r.status_code == 429:
        wait = r.headers.get("retry-after")
        raise ApiError(f"PreJudge is rate limiting this IP: {_detail(r)}"
                       + (f" (retry after {wait}s)." if wait else ""))
    if r.status_code == 404:
        raise ApiError("No such audit (check the id).")
    if r.status_code == 410:
        raise ApiError("This audit was removed at the owner's request.")
    if r.status_code >= 400:
        raise ApiError(f"PreJudge said {r.status_code}: {_detail(r)}")
    return r.json()


def _detail(r: httpx.Response) -> str:
    try:
        d = r.json().get("detail")
        return d if isinstance(d, str) else str(d)
    except Exception:
        return r.text[:200]


def _fixes(result: dict) -> list[dict]:
    fixes = (result.get("verdict") or {}).get("fixes") or []
    if fixes:
        return [{"title": f.get("title"), "points": f.get("points"), "fix": f.get("fix")} for f in fixes]
    return [{"title": f.get("title"), "points": f.get("points"), "fix": f.get("detail")}
            for f in (result.get("score") or {}).get("fix_candidates") or []]


def summarize(audit: dict) -> dict:
    """The part an agent needs: score, phase, roast, fixes, what failed. Links to the full result."""
    r = audit.get("result") or {}
    score = r.get("score") or {}
    out = {
        "audit_id": audit["id"],
        "url": f"{API}/a/{audit['id']}",
        "repo": audit.get("repo_url"),
        "status": audit["status"],
        "deep_check": (audit.get("phases") or {}).get("deep"),
    }
    if not r:
        return {**out, "note": "No result yet; call get_result again in a few seconds."}
    claims = (r.get("agent") or {}).get("claims") or []
    return {
        **out,
        "score": score.get("score"),
        "phase": "deep" if audit["status"] == "complete" else "quick",
        "categories": {c["id"]: f"{c['points']}/{c['max_points']}" for c in score.get("categories", [])},
        "roast": (r.get("verdict") or {}).get("roast"),
        "top_fixes": _fixes(r)[:3],
        "not_passing": [{"check": c["id"], "status": c["status"], "detail": c["detail"]}
                        for c in r.get("checks", []) if c["status"] not in ("pass",)],
        "claims": ({"verified": sum(c["status"] == "verified" for c in claims), "total": len(claims)}
                   if claims else None),
        "progress": (r.get("progress") or {}).get("text"),
    }


async def _wait(audit_id: str, done: tuple[str, ...], timeout: float, deep: bool = False) -> dict:
    end = time.monotonic() + timeout
    while True:
        a = await _call("GET", f"/api/audits/{audit_id}")
        state = (a.get("phases") or {}).get("deep") if deep else a["status"]
        if state in done or a["status"] in ("failed",) or time.monotonic() > end:
            return a
        await asyncio.sleep(POLL_S)


@mcp.tool()
async def audit_repo(repo_url: str) -> dict:
    """Audit a public GitHub repo against the neatHack rubric (quick phase, ~15s): score 0-100, a roast,
    the top fixes and what didn't pass. Returns an audit_id for deep_check / get_result / next_fix."""
    global _last_audit
    gap = MIN_GAP_S - (time.monotonic() - _last_audit)
    if gap > 0:
        await asyncio.sleep(gap)
    _last_audit = time.monotonic()
    try:
        created = await _call("POST", "/api/audits", json={"repo_url": repo_url})
        audit = await _wait(created["id"], ("quick_ready", "complete", "failed"), QUICK_WAIT_S)
    except ApiError as e:
        return {"error": str(e)}
    out = summarize(audit)
    if created.get("cached") or (audit.get("result") or {}).get("reuse"):
        out["note"] = "No new commits since the last check, so this is that result."
    return out


@mcp.tool()
async def deep_check(audit_id: str, wait: bool = True) -> dict:
    """Run the deep check: reads the code and verifies every README claim with file:line evidence,
    then rescores. Waits for it (up to ~7 minutes) unless wait is false."""
    try:
        q = await _call("POST", f"/api/audits/{audit_id}/deep")
        if q.get("status") == "complete" or q.get("phase_deep") == "done":
            return {**summarize(await _call("GET", f"/api/audits/{audit_id}")), "note": "The deep check already ran."}
        if not wait:
            return {"audit_id": audit_id, "queued": q.get("phase_deep"), "queue": q.get("queue"),
                    "note": "Call get_result later."}
        audit = await _wait(audit_id, ("done", "failed", "skipped"), DEEP_WAIT_S, deep=True)
    except ApiError as e:
        return {"error": str(e)}
    out = summarize(audit)
    if out.get("deep_check") not in ("done",):
        out["note"] = "The deep check is still queued or waiting for budget; call get_result later."
    return out


@mcp.tool()
async def get_result(audit_id: str) -> dict:
    """The current result of an audit: score, phase (quick/deep), roast, top fixes, checks not passing."""
    try:
        return summarize(await _call("GET", f"/api/audits/{audit_id}"))
    except ApiError as e:
        return {"error": str(e)}


@mcp.tool()
async def next_fix(audit_id: str) -> dict:
    """The single fix worth the most points right now, with how to do it."""
    try:
        a = await _call("GET", f"/api/audits/{audit_id}")
    except ApiError as e:
        return {"error": str(e)}
    fixes = _fixes(a.get("result") or {})
    if not fixes:
        return {"audit_id": audit_id, "next_fix": None, "note": "Nothing left to fix, or no result yet."}
    return {"audit_id": audit_id, "next_fix": fixes[0], "then": [f["title"] for f in fixes[1:3]],
            "url": f"{API}/a/{audit_id}"}


def main() -> None:
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
