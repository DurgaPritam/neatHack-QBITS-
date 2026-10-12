"""Offline tests (no network) + an end-to-end run over stdio against the live API (PREJUDGE_E2E=1)."""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

import prejudge_mcp as P

AUDIT = {"id": "abc123def456", "repo_url": "https://github.com/team/app", "status": "quick_ready",
         "phases": {"quick": "done", "deep": "available"},
         "result": {"score": {"score": 61, "categories": [{"id": "demo_video", "points": 0, "max_points": 20}],
                              "fix_candidates": []},
                    "verdict": {"roast": "ouch", "fixes": [
                        {"title": "Demo video", "points": 20.0, "fix": "Record a 3-minute demo."},
                        {"title": "Traces", "points": 2.6, "fix": "Add screenshots."}]},
                    "checks": [{"id": "demo_video", "status": "fail", "detail": "no video"},
                               {"id": "repo_public", "status": "pass", "detail": "public"}]}}


def test_summary_has_score_fixes_and_failures():
    s = P.summarize(AUDIT)
    assert s["score"] == 61 and s["phase"] == "quick" and s["url"].endswith("/a/abc123def456")
    assert s["top_fixes"][0]["title"] == "Demo video" and [c["check"] for c in s["not_passing"]] == ["demo_video"]


def test_next_fix_and_rate_limit_message(monkeypatch):
    async def ok(method, path, **kw):
        return AUDIT
    monkeypatch.setattr(P, "_call", ok)
    r = asyncio.run(P.next_fix("abc123def456"))
    assert r["next_fix"]["fix"] == "Record a 3-minute demo." and r["then"] == ["Traces"]

    async def limited(method, path, **kw):
        raise P.ApiError("PreJudge is rate limiting this IP: Easy there (retry after 120s).")
    monkeypatch.setattr(P, "_call", limited)
    monkeypatch.setattr(P, "MIN_GAP_S", 0)
    assert "retry after 120s" in asyncio.run(P.audit_repo("https://github.com/team/app"))["error"]


def test_new_audits_are_spaced_out(monkeypatch):
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    async def created(method, path, **kw):
        return {"id": "abc123def456"} if method == "POST" else AUDIT
    monkeypatch.setattr(P, "_call", created)
    monkeypatch.setattr(P.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(P, "_last_audit", 0.0)
    asyncio.run(P.audit_repo("https://github.com/team/app"))
    asyncio.run(P.audit_repo("https://github.com/team/app"))
    assert slept and slept[0] > P.MIN_GAP_S - 2          # the second call waited


@pytest.mark.skipif(not os.environ.get("PREJUDGE_E2E"), reason="set PREJUDGE_E2E=1 to hit the live API")
def test_end_to_end_over_stdio():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    repo = os.environ.get("PREJUDGE_E2E_REPO", "https://github.com/DurgaPritam/neatHack-QBITS-")

    async def run():
        params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).with_name("prejudge_mcp.py"))],
                                       env={**os.environ})
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            assert names == {"audit_repo", "deep_check", "get_result", "next_fix"}

            def data(res):
                return json.loads(res.content[0].text)
            a = data(await s.call_tool("audit_repo", {"repo_url": repo}))
            assert "error" not in a, a
            assert isinstance(a["score"], int) and a["audit_id"] and a["top_fixes"]
            g = data(await s.call_tool("get_result", {"audit_id": a["audit_id"]}))
            assert g["audit_id"] == a["audit_id"] and g["score"] == a["score"]
            n = data(await s.call_tool("next_fix", {"audit_id": a["audit_id"]}))
            assert n["next_fix"]["title"]
            d = data(await s.call_tool("deep_check", {"audit_id": a["audit_id"], "wait": False}))
            assert "audit_id" in d or "error" in d
            bad = data(await s.call_tool("get_result", {"audit_id": "000000000000"}))
            assert "No such audit" in bad["error"]
            return a, n, d
    a, n, d = asyncio.run(run())
    print("\nE2E:", json.dumps({"score": a["score"], "phase": a["phase"], "next_fix": n["next_fix"]["title"],
                                "deep": d}, default=str))
