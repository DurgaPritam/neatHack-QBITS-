import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app import db, jobs, main


class Gate:
    """Lets a test hold the deep phase open to prove quick results don't wait for it."""

    def __init__(self):
        self.open = True


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PREJUDGE_DB", str(tmp_path / "t.db"))
    calls = {"quick": [], "deep": []}
    gate = Gate()

    async def fake_quick(repo_url, audit_id, run_kind, steps, ctx):
        calls["quick"].append(repo_url)
        steps.note("github.get_repo", "ok")
        ctx["repo_available"] = True
        await asyncio.sleep(0.02)
        return {"audit_id": audit_id, "repo_url": repo_url, "phase": "quick", "score": {"score": 30},
                "verdict": {"source": "llm", "roast": "quick roast"}, "steps": steps.to_list()}

    async def fake_deep(report, ctx, steps):
        calls["deep"].append(report["repo_url"])
        while not gate.open:
            await asyncio.sleep(0.01)
        steps.note("llm.claims", "ok")
        source = "template" if "flaky" in report["repo_url"] else "llm"
        return {**report, "phase": "complete", "score": {"score": 42},
                "verdict": {"source": source, "roast": "deep roast"}, "steps": steps.to_list()}

    async def fake_sha(repo_url):
        return "deadbeef"

    monkeypatch.setattr(jobs, "_run_quick", fake_quick)
    monkeypatch.setattr(jobs, "_run_deep", fake_deep)
    monkeypatch.setattr(main, "resolve_head_sha", fake_sha)
    with TestClient(main.app) as c:
        db.connect(tmp_path / "t.db")
        c.calls, c.gate = calls, gate
        yield c


def wait_for(c, audit_id, statuses, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        r = c.get(f"/api/audits/{audit_id}").json()
        if r["status"] in statuses:
            return r
        time.sleep(0.01)
    raise AssertionError(f"audit never reached {statuses}: {r}")


def post(c, repo, **kw):
    return c.post("/api/audits", json={"repo_url": repo, **kw})


def test_quick_ready_then_complete(client):
    r = post(client, "https://github.com/acme/demo")
    assert r.status_code == 202 and r.json()["status"] == "queued"
    assert r.json()["queue"]["lane"] == "quick"
    quick = wait_for(client, r.json()["id"], ("quick_ready", "complete"))
    done = wait_for(client, r.json()["id"], ("complete",))
    assert done["result"]["score"]["score"] == 42 and done["phases"] == {"quick": "done", "deep": "done"}
    assert [s["name"] for s in done["steps"]] == ["github.get_repo", "llm.claims"]
    assert client.get("/api/stats").json() == {"total_audits": 1, "completed_audits": 1, "including_test_runs": 1}
    assert quick["result"]["score"]["score"] in (30, 42)


def test_quick_result_never_waits_on_deep(client):
    client.gate.open = False  # deep phase blocked
    a = post(client, "https://github.com/acme/one").json()["id"]
    first = wait_for(client, a, ("quick_ready",))
    assert first["result"]["verdict"]["roast"] == "quick roast"
    assert first["phases"]["quick"] == "done" and first["phases"]["deep"] in ("queued", "running")
    # a second audit still gets its quick result while the first is stuck in deep
    b = post(client, "https://github.com/acme/two").json()["id"]
    second = wait_for(client, b, ("quick_ready",))
    assert second["queue"]["lane"] == "deep" and second["queue"]["position"] == 2
    assert second["queue"]["estimated_wait_s"] > 0
    client.gate.open = True
    wait_for(client, a, ("complete",))
    wait_for(client, b, ("complete",))


def test_cache_by_repo_and_sha(client):
    first = post(client, "https://github.com/acme/demo").json()
    wait_for(client, first["id"], ("complete",))
    second = post(client, "github.com/ACME/demo").json()
    assert second["cached"] is True and second["status"] == "complete"
    got = client.get(f"/api/audits/{second['id']}").json()
    assert got["result"]["cached_from"] == first["id"] and got["result"]["audit_id"] == second["id"]
    assert len(client.calls["quick"]) == 1


def test_same_commit_in_progress_is_deduplicated(client):
    client.gate.open = False
    first = post(client, "https://github.com/acme/demo").json()
    wait_for(client, first["id"], ("quick_ready",))
    again = post(client, "https://github.com/acme/demo").json()
    assert again["id"] == first["id"] and again["deduplicated"] is True
    client.gate.open = True
    wait_for(client, first["id"], ("complete",))


def test_degraded_results_are_not_cached(client):
    a = post(client, "https://github.com/acme/flaky").json()
    wait_for(client, a["id"], ("complete",))
    b = post(client, "https://github.com/acme/flaky").json()
    assert b["cached"] is False and b.get("deduplicated") is None


def test_test_runs_excluded_from_public_counter(client):
    r = post(client, "https://github.com/acme/demo", run_kind="test")
    wait_for(client, r.json()["id"], ("complete",))
    s = client.get("/api/stats").json()
    assert s["total_audits"] == 0 and s["including_test_runs"] == 1


def test_deep_runs_one_at_a_time(client, monkeypatch):
    running, peak = {"n": 0}, {"n": 0}

    async def slow(report, ctx, steps):
        running["n"] += 1
        peak["n"] = max(peak["n"], running["n"])
        await asyncio.sleep(0.03)
        running["n"] -= 1
        return {**report, "phase": "complete", "verdict": {"source": "llm"}, "steps": []}

    monkeypatch.setattr(jobs, "_run_deep", slow)
    ids = [post(client, f"https://github.com/acme/r{i}").json()["id"] for i in range(3)]
    for i in ids:
        wait_for(client, i, ("complete",))
    assert peak["n"] == 1


def test_quick_crash_is_recorded(client, monkeypatch):
    async def boom(*a):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(jobs, "_run_quick", boom)
    r = post(client, "https://github.com/acme/x").json()
    done = wait_for(client, r["id"], ("failed",))
    assert done["steps"][-1]["name"] == "quick.crashed" and done["phases"]["deep"] == "skipped"


def test_deep_crash_keeps_quick_result(client, monkeypatch):
    async def boom(*a):
        raise RuntimeError("deep kaboom")

    monkeypatch.setattr(jobs, "_run_deep", boom)
    r = post(client, "https://github.com/acme/x").json()
    end = time.time() + 5
    while time.time() < end:
        got = client.get(f"/api/audits/{r['id']}").json()
        if got["phases"]["deep"] == "failed":
            break
        time.sleep(0.01)
    assert got["status"] == "quick_ready" and got["result"]["verdict"]["roast"] == "quick roast"
    assert got["steps"][-1]["name"] == "deep.crashed"


def test_restart_marks_interrupted_jobs(tmp_path):
    db.connect(tmp_path / "restart.db")
    db.create("a1", "u", "acme/a", "s", "real")                       # queued
    db.create("a2", "u", "acme/b", "s", "real", status="quick_ready", phase_deep="queued")
    assert db.mark_interrupted() == 2
    assert db.get("a1")["status"] == "failed"
    assert db.get("a2")["status"] == "quick_ready" and db.get("a2")["phase_deep"] == "failed"


def test_bad_input_and_404_and_cors(client):
    assert post(client, "not a url").status_code == 400
    assert client.get("/api/audits/nope").status_code == 404
    r = client.options("/api/audits", headers={"Origin": "http://localhost:5173",
                                               "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
