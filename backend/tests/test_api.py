import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app import db, jobs, main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PREJUDGE_DB", str(tmp_path / "t.db"))
    calls = []

    async def fake_run(repo_url, audit_id, run_kind, steps):
        calls.append(repo_url)
        steps.note("github.get_repo", "ok")
        await asyncio.sleep(0.05)
        steps.note("llm.claims", "ok")
        source = "template" if "flaky" in repo_url else "llm"
        return {"audit_id": audit_id, "score": {"score": 42}, "verdict": {"source": source},
                "steps": steps.to_list()}

    async def fake_sha(repo_url):
        return "deadbeef"

    monkeypatch.setattr(jobs, "_run", fake_run)
    monkeypatch.setattr(main, "resolve_head_sha", fake_sha)
    with TestClient(main.app) as c:
        db.connect(tmp_path / "t.db")
        c.calls = calls
        yield c


def wait_done(c, audit_id, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        r = c.get(f"/api/audits/{audit_id}").json()
        if r["status"] in ("done", "failed"):
            return r
        time.sleep(0.02)
    raise AssertionError("audit did not finish")


def test_create_poll_and_stats(client):
    r = client.post("/api/audits", json={"repo_url": "https://github.com/acme/demo"})
    assert r.status_code == 202 and r.json()["status"] == "queued"
    done = wait_done(client, r.json()["id"])
    assert done["result"]["score"]["score"] == 42
    assert [s["name"] for s in done["steps"]] == ["github.get_repo", "llm.claims"]
    assert client.get("/api/stats").json()["total_audits"] == 1


def test_cache_by_repo_and_sha(client):
    first = client.post("/api/audits", json={"repo_url": "https://github.com/acme/demo"}).json()
    wait_done(client, first["id"])
    second = client.post("/api/audits", json={"repo_url": "github.com/ACME/demo"}).json()
    assert second["cached"] is True and second["status"] == "done"
    got = client.get(f"/api/audits/{second['id']}").json()
    assert got["result"]["cached_from"] == first["id"] and got["result"]["audit_id"] == second["id"]
    assert len(client.calls) == 1  # audit ran once
    assert client.get("/api/stats").json()["total_audits"] == 2


def test_degraded_results_are_not_cached(client):
    a = client.post("/api/audits", json={"repo_url": "https://github.com/acme/flaky"}).json()
    wait_done(client, a["id"])
    b = client.post("/api/audits", json={"repo_url": "https://github.com/acme/flaky"}).json()
    assert b["cached"] is False


def test_test_runs_excluded_from_public_counter(client):
    r = client.post("/api/audits", json={"repo_url": "https://github.com/acme/demo", "run_kind": "test"})
    wait_done(client, r.json()["id"])
    s = client.get("/api/stats").json()
    assert s["total_audits"] == 0 and s["including_test_runs"] == 1


def test_queue_runs_one_at_a_time(client, monkeypatch):
    running, peak = {"n": 0}, {"n": 0}

    async def slow(repo_url, audit_id, run_kind, steps):
        running["n"] += 1
        peak["n"] = max(peak["n"], running["n"])
        await asyncio.sleep(0.05)
        running["n"] -= 1
        return {"verdict": {"source": "llm"}, "steps": []}

    monkeypatch.setattr(jobs, "_run", slow)
    ids = [client.post("/api/audits", json={"repo_url": f"https://github.com/acme/r{i}"}).json()["id"]
           for i in range(3)]
    for i in ids:
        wait_done(client, i)
    assert peak["n"] == 1


def test_crash_is_recorded_not_raised(client, monkeypatch):
    async def boom(*a):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(jobs, "_run", boom)
    r = client.post("/api/audits", json={"repo_url": "https://github.com/acme/x"}).json()
    done = wait_done(client, r["id"])
    assert done["status"] == "failed" and done["steps"][-1]["name"] == "audit.crashed"


def test_bad_input_and_404_and_cors(client):
    assert client.post("/api/audits", json={"repo_url": "not a url"}).status_code == 400
    assert client.get("/api/audits/nope").status_code == 404
    r = client.options("/api/audits", headers={"Origin": "http://localhost:5173",
                                               "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
