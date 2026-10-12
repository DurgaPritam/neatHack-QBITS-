import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app import db, jobs, limits, main
from app.tools.rubric import CHECKS_VERSION


class Gate:
    """Lets a test hold the deep phase open."""

    def __init__(self):
        self.open = True


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PREJUDGE_DB", str(tmp_path / "t.db"))
    calls = {"quick": [], "deep": [], "reserve": []}
    gate = Gate()

    async def fake_quick(repo_url, audit_id, run_kind, steps, ctx, use_reserve=False):
        calls["quick"].append(repo_url)
        calls["reserve"].append(("quick", use_reserve))
        steps.note("github.get_repo", "ok")
        ctx["repo_available"] = "missing" not in repo_url
        await asyncio.sleep(0.02)
        source = "template" if "flaky" in repo_url else "llm"
        return {"audit_id": audit_id, "repo_url": repo_url, "phase": "quick", "score": {"score": 30},
                "checks_version": CHECKS_VERSION,
                "verdict": {"source": source, "roast": "quick roast"}, "steps": steps.to_list()}

    async def fake_deep(report, ctx, steps, use_reserve=False):
        calls["deep"].append(report["repo_url"])
        calls["reserve"].append(("deep", use_reserve))
        while not gate.open:
            await asyncio.sleep(0.01)
        steps.note("llm.claims", "ok")
        return {**report, "phase": "complete", "score": {"score": 42},
                "verdict": {"source": "llm", "roast": "deep roast"}, "steps": steps.to_list()}

    async def fake_rebuild(report):
        return {"repo_available": True, "rebuilt": True}

    async def fake_sha(repo_url):
        return "deadbeef"

    monkeypatch.setattr(jobs, "_run_quick", fake_quick)
    monkeypatch.setattr(jobs, "_run_deep", fake_deep)
    monkeypatch.setattr(jobs, "_rebuild_ctx", fake_rebuild)
    monkeypatch.setattr(main, "resolve_head_sha", fake_sha)
    # abuse limits get their own tests; elsewhere they'd only get in the way
    limits.reset_all()
    for lane in (main.queues.quick, main.queues.deep):  # module-level queues outlive a TestClient
        lane.pending.clear()
        lane.running = None
    monkeypatch.setattr(limits, "REPO_COOLDOWN_S", 0)
    monkeypatch.setattr(limits.AUDITS, "limit", 1000)
    monkeypatch.setattr(limits.DEEP, "limit", 1000)
    with TestClient(main.app) as c:
        c.calls, c.gate = calls, gate
        yield c


def wait_for(c, audit_id, statuses, timeout=5, key="status"):
    end = time.time() + timeout
    while time.time() < end:
        r = c.get(f"/api/audits/{audit_id}").json()
        val = r["phases"]["deep"] if key == "deep" else r[key]
        if val in statuses:
            return r
        time.sleep(0.01)
    raise AssertionError(f"audit never reached {statuses}: {r}")


def post(c, repo, **kw):
    return c.post("/api/audits", json={"repo_url": repo, **kw.pop("body", {})}, **kw)


def test_quick_only_by_default(client):
    r = post(client, "https://github.com/acme/demo")
    assert r.status_code == 202 and r.json()["status"] == "queued" and r.json()["queue"]["lane"] == "quick"
    quick = wait_for(client, r.json()["id"], ("quick_ready",))
    assert quick["phases"] == {"quick": "done", "deep": "available"}
    time.sleep(0.1)
    assert client.calls["deep"] == []  # deep never starts on its own


def test_deep_on_request_then_complete(client):
    aid = post(client, "https://github.com/acme/demo").json()["id"]
    wait_for(client, aid, ("quick_ready",))
    d = client.post(f"/api/audits/{aid}/deep")
    assert d.status_code == 202 and d.json()["queue"]["lane"] == "deep"
    assert {"position", "estimated_wait_s"} <= set(d.json()["queue"])
    done = wait_for(client, aid, ("complete",))
    assert done["result"]["score"]["score"] == 42 and done["phases"]["deep"] == "done"
    assert [s["name"] for s in done["steps"]] == ["github.get_repo", "llm.claims"]  # one continuous log
    again = client.post(f"/api/audits/{aid}/deep").json()
    assert again["status"] == "complete" and len(client.calls["deep"]) == 1


def test_deep_queue_positions_and_one_at_a_time(client):
    client.gate.open = False
    ids = [post(client, f"https://github.com/acme/r{i}").json()["id"] for i in range(3)]
    for i in ids:
        wait_for(client, i, ("quick_ready",))
    queued = [client.post(f"/api/audits/{i}/deep").json()["queue"] for i in ids]
    assert [q["position"] for q in queued] == [1, 2, 3]
    assert queued[2]["estimated_wait_s"] > queued[1]["estimated_wait_s"]
    assert client.get("/api/stats").json()["deep_queue"] == 3
    client.gate.open = True
    for i in ids:
        wait_for(client, i, ("complete",))


def test_deep_waits_for_judge_budget_instead_of_degrading(client, monkeypatch):
    ok = {"v": False}
    monkeypatch.setattr(jobs, "deep_budget_ok", lambda use_reserve: ok["v"])
    monkeypatch.setattr(jobs, "BUDGET_RECHECK_S", 0.05)
    aid = post(client, "https://github.com/acme/demo").json()["id"]
    wait_for(client, aid, ("quick_ready",))
    client.post(f"/api/audits/{aid}/deep")
    waiting = wait_for(client, aid, ("waiting_budget",), key="deep")
    assert waiting["queue"]["waiting_for_budget"] is True and client.calls["deep"] == []
    ok["v"] = True
    wait_for(client, aid, ("complete",))


def test_admin_token_unlocks_reserve(client):
    a = post(client, "https://github.com/acme/admin", headers={"X-Admin-Token": "test-admin-token"}).json()["id"]
    wait_for(client, a, ("quick_ready",))
    client.post(f"/api/audits/{a}/deep", headers={"X-Admin-Token": "test-admin-token"})
    wait_for(client, a, ("complete",))
    b = post(client, "https://github.com/acme/public", headers={"X-Admin-Token": "wrong"}).json()["id"]
    wait_for(client, b, ("quick_ready",))
    assert client.calls["reserve"] == [("quick", True), ("deep", True), ("quick", False)]


def test_deep_after_context_expired_rebuilds_without_llm(client):
    aid = post(client, "https://github.com/acme/demo").json()["id"]
    wait_for(client, aid, ("quick_ready",))
    main.queues.ctx_cache.clear()
    client.post(f"/api/audits/{aid}/deep")
    done = wait_for(client, aid, ("complete",))
    assert "deep.rebuild_context" in [s["name"] for s in done["steps"]]


def test_deep_rejected_when_not_possible(client):
    aid = post(client, "https://github.com/acme/missing").json()["id"]
    r = wait_for(client, aid, ("quick_ready",))
    assert r["phases"]["deep"] == "skipped"
    assert client.post(f"/api/audits/{aid}/deep").status_code == 409
    assert client.post("/api/audits/nope/deep").status_code == 404


def test_cache_reuses_quick_and_complete_results(client):
    first = post(client, "https://github.com/acme/demo").json()
    wait_for(client, first["id"], ("quick_ready",))
    again = post(client, "github.com/ACME/demo").json()
    assert again["cached"] is True and again["status"] == "quick_ready"
    client.post(f"/api/audits/{first['id']}/deep")
    wait_for(client, first["id"], ("complete",))
    third = post(client, "https://github.com/acme/demo").json()
    assert third["status"] == "complete"
    assert client.get(f"/api/audits/{third['id']}").json()["result"]["cached_from"] == first["id"]
    assert len(client.calls["quick"]) == 1


def test_template_results_are_not_cached(client):
    a = post(client, "https://github.com/acme/flaky").json()
    wait_for(client, a["id"], ("quick_ready",))
    b = post(client, "https://github.com/acme/flaky").json()
    assert b["cached"] is False and b.get("deduplicated") is None


def test_stats_counter_states_and_test_runs(client, monkeypatch):
    base = client.get("/api/stats").json()
    assert base["budget_state"] == "normal"
    r = post(client, "https://github.com/acme/demo", body={"run_kind": "test"})
    wait_for(client, r.json()["id"], ("quick_ready",))
    s = client.get("/api/stats").json()
    assert s["total_audits"] == base["total_audits"]
    assert s["including_test_runs"] == base["including_test_runs"] + 1
    monkeypatch.setattr(main.queues, "busy", lambda: True)
    assert client.get("/api/stats").json()["budget_state"] == "busy"
    monkeypatch.setattr(main.POOL, "budget", lambda *a, **k: {"public_available": False})
    monkeypatch.setattr(main.replay, "mode", lambda: "live")
    assert client.get("/api/stats").json()["budget_state"] == "cooling"


def test_examples_are_the_saved_real_audits(client):
    ex = client.get("/api/examples").json()
    assert {e["repo"] for e in ex} == {"openai/swarm", "huggingface/smolagents", "langchain-ai/open_deep_research"}
    assert all(e["roast"] and isinstance(e["score"], int) for e in ex)
    full = client.get(f"/api/audits/{ex[0]['id']}").json()
    assert full["status"] == "complete" and full["result"]["agent"]["claims"]


def test_feedback(client):
    aid = client.get("/api/examples").json()[0]["id"]
    r = client.post(f"/api/audits/{aid}/feedback", json={"check_id": "demo_video", "note": "it's 2:59"})
    assert r.status_code == 201 and db.feedback_for(aid) == [{"check_id": "demo_video", "is_wrong": 1,
                                                              "note": "it's 2:59"}]
    assert client.post("/api/audits/nope/feedback", json={"check_id": "x"}).status_code == 404
    assert client.post(f"/api/audits/{aid}/feedback", json={"check_id": ""}).status_code == 422


def test_quick_crash_is_recorded(client, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(jobs, "_run_quick", boom)
    r = post(client, "https://github.com/acme/x").json()
    done = wait_for(client, r["id"], ("failed",))
    assert done["steps"][-1]["name"] == "quick.crashed" and done["phases"]["deep"] == "skipped"


def test_deep_crash_keeps_quick_result(client, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("deep kaboom")

    monkeypatch.setattr(jobs, "_run_deep", boom)
    aid = post(client, "https://github.com/acme/x").json()["id"]
    wait_for(client, aid, ("quick_ready",))
    client.post(f"/api/audits/{aid}/deep")
    got = wait_for(client, aid, ("failed",), key="deep")
    assert got["status"] == "quick_ready" and got["result"]["verdict"]["roast"] == "quick roast"
    assert got["steps"][-1]["name"] == "deep.crashed"


def test_restart_marks_interrupted_jobs(tmp_path):
    db.connect(tmp_path / "restart.db")
    db.create("a1", "u", "acme/a", "s", "real")
    db.create("a2", "u", "acme/b", "s", "real", status="quick_ready", phase_deep="running")
    assert db.mark_interrupted() == 2
    assert db.get("a1")["status"] == "failed"
    assert db.get("a2")["phase_deep"] == "available"  # user can ask for the deep check again


def test_bad_input_and_404_and_cors(client):
    assert post(client, "not a url").status_code == 400
    assert client.get("/api/audits/nope").status_code == 404
    r = client.options("/api/audits", headers={"Origin": "http://localhost:5173",
                                               "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


ADMIN = {"X-Admin-Token": "test-admin-token"}


def test_ip_rate_limit_on_new_audits(client, monkeypatch):
    monkeypatch.setattr(limits.AUDITS, "limit", 2)
    assert post(client, "https://github.com/acme/a1").status_code == 202
    assert post(client, "https://github.com/acme/a2").status_code == 202
    r = post(client, "https://github.com/acme/a3")
    assert r.status_code == 429 and "2 new audits per 10 minutes" in r.json()["detail"]
    assert int(r.headers["retry-after"]) > 0
    assert post(client, "https://github.com/acme/a4", headers=ADMIN).status_code == 202  # admin exempt


def test_repo_cooldown_reuses_recent_audit(client, monkeypatch):
    monkeypatch.setattr(limits, "REPO_COOLDOWN_S", 600)
    monkeypatch.setattr(limits.AUDITS, "limit", 1)
    first = post(client, "https://github.com/acme/flaky").json()   # template result: not sha-cached
    wait_for(client, first["id"], ("quick_ready",))
    again = post(client, "https://github.com/ACME/flaky").json()
    assert again == {"id": first["id"], "status": "quick_ready", "cached": True, "cooldown": True}
    assert len(client.calls["quick"]) == 1

    async def pushed(repo_url):
        return "c0ffee"  # the team pushed a fix: re-auditing must not return the stale result
    monkeypatch.setattr(main, "resolve_head_sha", pushed)
    monkeypatch.setattr(limits.AUDITS, "limit", 5)
    fresh = post(client, "https://github.com/acme/flaky").json()
    assert fresh["id"] != first["id"] and fresh["cached"] is False


def test_deep_limits_and_queue_full(client, monkeypatch):
    ids = [post(client, f"https://github.com/acme/d{i}").json()["id"] for i in range(4)]
    for i in ids:
        wait_for(client, i, ("quick_ready",))
    client.gate.open = False                       # hold the deep lane so the queue fills
    monkeypatch.setattr(limits, "DEEP_QUEUE_MAX", 2)
    assert client.post(f"/api/audits/{ids[0]}/deep").status_code == 202
    assert client.post(f"/api/audits/{ids[1]}/deep").status_code == 202
    assert client.post(f"/api/audits/{ids[1]}/deep").status_code == 202   # re-asking is free
    full = client.post(f"/api/audits/{ids[2]}/deep")
    assert full.status_code == 503 and "queue is full" in full.json()["detail"]
    monkeypatch.setattr(limits, "DEEP_QUEUE_MAX", 100)
    monkeypatch.setattr(limits.DEEP, "limit", 2)
    limits.DEEP.reset()
    assert client.post(f"/api/audits/{ids[2]}/deep").status_code == 202
    assert client.post(f"/api/audits/{ids[3]}/deep").status_code == 202
    extra = post(client, "https://github.com/acme/d9").json()["id"]
    wait_for(client, extra, ("quick_ready",))
    r = client.post(f"/api/audits/{extra}/deep")
    assert r.status_code == 429 and "deep checks for this hour" in r.json()["detail"]
    client.gate.open = True


def test_removal_hides_and_admin_restores(client):
    aid = post(client, "https://github.com/acme/demo").json()["id"]
    wait_for(client, aid, ("quick_ready",))
    assert client.post(f"/api/audits/{aid}/removal", json={"reason": "mine, please remove"}).json()["hidden"]
    for path in (f"/api/audits/{aid}", f"/api/audits/{aid}/card.png", f"/r/{aid}"):
        assert client.get(path).status_code == 410, path
    gone = client.get(f"/r/{aid}")
    assert f"/a/{aid}" in gone.text and "og:image" not in gone.text  # humans land on the app's page
    assert client.get("/r/nope").status_code == 404 and "/a/nope" in client.get("/r/nope").text
    assert client.get(f"/api/audits/{aid}", headers=ADMIN).json()["hidden"] is True
    assert client.get("/api/admin/removals").status_code == 401
    removed = client.get("/api/admin/removals", headers=ADMIN).json()
    assert removed[0]["id"] == aid and removed[0]["hidden_reason"] == "mine, please remove"
    assert client.post(f"/api/admin/audits/{aid}/restore", headers=ADMIN).json() == {"ok": True, "hidden": False}
    assert client.get(f"/api/audits/{aid}").status_code == 200
    assert client.post("/api/audits/nope/removal").status_code == 404


def test_admin_feedback_export_and_metrics(client):
    aid = post(client, "https://github.com/acme/demo").json()["id"]
    wait_for(client, aid, ("quick_ready",))
    client.post(f"/api/audits/{aid}/feedback", json={"check_id": "demo_video", "note": "=HYPERLINK(1)"})
    assert client.get("/api/admin/feedback").status_code == 401
    assert client.get("/api/admin/feedback", headers={"X-Admin-Token": "wrong"}).status_code == 401
    rows = client.get("/api/admin/feedback", headers=ADMIN).json()
    assert rows[0]["check_id"] == "demo_video" and rows[0]["repo_url"].endswith("acme/demo")
    csv_r = client.get("/api/admin/feedback?format=csv", headers=ADMIN)
    assert csv_r.headers["content-type"].startswith("text/csv") and "'=HYPERLINK(1)" in csv_r.text
    client.get(f"/api/audits/{aid}/card.png")
    for name in ("card_download", "share_x", "share_x"):
        assert client.post("/api/events", json={"name": name}).status_code == 204
    assert client.post("/api/events", json={"name": "page_view"}).status_code == 422
    client.post(f"/api/audits/{aid}/deep")
    wait_for(client, aid, ("complete",))
    m = client.get("/api/admin/metrics", headers=ADMIN).json()
    t = m["totals"]
    assert (t["audits"], t["card_download"], t["share_x"], t["card_png"]) == (1, 1, 2, 1)
    assert t["deep_requested"] == 1 and t["deep_completed"] == 1 and m["days"][0]["day"]


def test_results_are_noindex(client):
    aid = post(client, "https://github.com/acme/demo").json()["id"]
    wait_for(client, aid, ("quick_ready",))
    page = client.get(f"/r/{aid}", follow_redirects=False)
    assert '<meta name="robots" content="noindex, nofollow">' in page.text
    assert page.headers["x-robots-tag"] == "noindex, nofollow"
    assert client.get(f"/api/audits/{aid}").headers["x-robots-tag"] == "noindex, nofollow"
    assert "x-robots-tag" not in client.get("/api/stats").headers


def test_public_counter_excludes_builtin_examples(client):
    assert len(client.get("/api/examples").json()) == 3
    assert client.get("/api/stats").json()["total_audits"] == 0
    aid = post(client, "https://github.com/acme/demo").json()["id"]
    wait_for(client, aid, ("quick_ready",))
    assert client.get("/api/stats").json()["total_audits"] == 1


def test_counter_is_roasts_and_unique_repos(client):
    for url in ("https://github.com/acme/demo", "https://github.com/acme/demo", "https://github.com/acme/other"):
        wait_for(client, post(client, url).json()["id"], ("quick_ready",))
    t = post(client, "https://github.com/acme/third", body={"run_kind": "test"}).json()["id"]
    wait_for(client, t, ("quick_ready",))
    s = client.get("/api/stats").json()
    assert s["total_audits"] == 3 and s["unique_repos"] == 2          # test runs and examples excluded
    from app import db
    other = [a for a in db.recent_audits(50) if a["repo_key"] == "acme/other"][0]["id"]
    db.set_hidden(other, True, "removed by owner")
    s = client.get("/api/stats").json()
    assert s["total_audits"] == 2 and s["unique_repos"] == 1          # removed audits excluded


def test_raw_step_errors_only_for_admins(client):
    aid = post(client, "https://github.com/acme/demo").json()["id"]
    wait_for(client, aid, ("quick_ready",))
    row = db.get(aid)
    db.update(aid, steps=row["steps"] + [{"name": "llm.verify", "status": "failed", "error_kind": "rate_limited",
                                          "detail": "Error code: 429 - {'error': 'raw'}", "duration_ms": 1, "data": {}}])
    public = client.get(f"/api/audits/{aid}").json()["steps"][-1]["detail"]
    admin = client.get(f"/api/audits/{aid}", headers=ADMIN).json()["steps"][-1]["detail"]
    assert "Error code" not in public and "Error code" in admin


def test_results_from_older_check_logic_are_not_reused(client):
    first = post(client, "https://github.com/acme/demo").json()
    wait_for(client, first["id"], ("quick_ready",))
    row = db.get(first["id"])
    db.update(first["id"], result={**row["result"], "checks_version": "old"})
    again = post(client, "https://github.com/acme/demo").json()
    assert again["cached"] is False and again["id"] != first["id"]


def test_showcase_is_opt_in_and_tops_up_with_examples(client):
    examples = {e["id"] for e in client.get("/api/examples").json()}
    feed = client.get("/api/showcase").json()
    assert {f["id"] for f in feed} == examples and all(f["example"] for f in feed)   # nobody opted in yet
    a = post(client, "https://github.com/acme/demo").json()["id"]
    b = post(client, "https://github.com/acme/other").json()["id"]
    wait_for(client, a, ("quick_ready",)); wait_for(client, b, ("quick_ready",))
    assert client.get(f"/api/audits/{a}").json()["showcase"] is False            # default off
    assert not any(f["id"] in (a, b) for f in client.get("/api/showcase").json())  # never without opting in
    assert client.post(f"/api/audits/{a}/showcase", json={"show": True}).json() == {"ok": True, "showcase": True}
    feed = client.get("/api/showcase").json()
    assert feed[0]["id"] == a and not feed[0]["example"] and feed[0]["roast"] == "quick roast"
    assert b not in {f["id"] for f in feed} and len(feed) == 3                   # 1 opted in + 2 examples
    db.set_hidden(a, True, "removed")                                             # removed: gone from the feed
    assert a not in {f["id"] for f in client.get("/api/showcase").json()}
    db.set_hidden(a, False)
    client.post(f"/api/audits/{a}/showcase", json={"show": False})                # opt out again
    assert a not in {f["id"] for f in client.get("/api/showcase").json()}
    assert client.post(f"/api/audits/{next(iter(examples))}/showcase", json={"show": False}).status_code == 400


def test_showcase_feed_newest_per_repo_max_six_no_templates_or_tests(client):
    ids = []
    for i in range(8):
        aid = post(client, f"https://github.com/acme/r{i}").json()["id"]
        wait_for(client, aid, ("quick_ready",))
        client.post(f"/api/audits/{aid}/showcase", json={"show": True})
        ids.append(aid)
        time.sleep(1.01)  # updated_at has second resolution
    flaky = post(client, "https://github.com/acme/flaky").json()["id"]   # template roast: not a roast
    test_run = post(client, "https://github.com/acme/t", body={"run_kind": "test"}).json()["id"]
    for x in (flaky, test_run):
        wait_for(client, x, ("quick_ready",))
        client.post(f"/api/audits/{x}/showcase", json={"show": True})
    feed = client.get("/api/showcase").json()
    assert [f["id"] for f in feed] == ids[::-1][:6] and not any(f["example"] for f in feed)
