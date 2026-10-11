"""M6: budget caps, same-commit reuse, project history + progress, percentiles, admin overview."""
import asyncio

import pytest

from app import db, history, jobs, limits, main
from app.llm import QuotaPool
from app.tools.rubric import CHECKS_VERSION
from tests.test_api import client, post, wait_for  # noqa: F401  (fixture)

ADMIN = {"X-Admin-Token": "test-admin-token"}


def checks(inside=5, **status):
    base = {"demo_video": "fail", "entire_checkpoints": "fail", "cfo_ai_plan": "fail",
            "before_after": "fail", "failure_recovery": "fail", **status}
    out = [{"id": "commits_in_window", "title": "Commits in window", "status": "pass" if inside else "fail",
            "detail": f"{inside} inside, 0 before start, 0 after close"}]
    out += [{"id": k, "title": k.replace("_", " "), "status": v, "detail": ""} for k, v in base.items()]
    return out


@pytest.fixture
def repo(client, monkeypatch):
    """Scriptable repo: set .sha, .score, .checks, .tokens before each audit."""
    state = type("S", (), {"sha": "sha1", "score": 46, "checks": checks(), "tokens": 2500, "source": "llm"})()

    async def fake_sha(repo_url):
        return state.sha

    async def fake_quick(repo_url, audit_id, run_kind, steps, ctx, use_reserve=False):
        ctx["repo_available"] = True
        steps.note("github.get_repo", "ok")
        return {"audit_id": audit_id, "repo_url": repo_url, "checks_version": CHECKS_VERSION,
                "score": {"score": state.score}, "checks": state.checks,
                "usage": {"total_tokens": state.tokens}, "verdict": {"source": state.source, "roast": "r"},
                "steps": steps.to_list()}

    monkeypatch.setattr(main, "resolve_head_sha", fake_sha)
    monkeypatch.setattr(jobs, "_run_quick", fake_quick)
    client.state = state
    return client


def audit(c, url="https://github.com/team/app", **kw):
    r = post(c, url, **kw).json()
    return r, wait_for(c, r["id"], {"quick_ready", "complete"})


# ---------------------------------------------------------------- 2. same commit = same result

def test_same_commit_returns_stored_result_without_llm(repo):
    first, _ = audit(repo)
    calls = len(repo.calls["quick"])
    again, body = audit(repo)
    assert again["cached"] and again["reuse"]["from"] == first["id"]
    assert len(repo.calls["quick"]) == calls  # no new quick phase
    assert body["result"]["reuse"]["tokens_saved"] == 2500 and "checked_at" in body["result"]["reuse"]
    assert db.today_count("tokens_saved") == 2500 and db.today_count("reused_audits") == 1


def test_reuse_has_no_time_limit_and_new_push_runs_fresh(repo):
    first, _ = audit(repo)
    db._db().execute("UPDATE audits SET created_at = '2026-01-01T00:00:00+00:00' WHERE id = ?", (first["id"],))
    db._db().commit()
    assert audit(repo)[0]["reuse"]["from"] == first["id"]
    repo.state.sha = "sha2"
    assert not audit(repo)[0]["cached"]


def test_template_verdict_is_retried_while_budget_allows(repo, monkeypatch):
    repo.state.source = "template"
    audit(repo)
    monkeypatch.setattr(main, "public_budget_ok", lambda: True)
    assert not audit(repo)[0]["cached"]
    monkeypatch.setattr(main, "public_budget_ok", lambda: False)  # budget gone: reuse it rather than redo it
    assert audit(repo)[0]["cached"]


def test_tokens_saved_in_admin_metrics(repo):
    audit(repo)
    audit(repo)
    m = repo.get("/api/admin/metrics", headers=ADMIN).json()
    assert m["totals"]["tokens_saved"] == 2500


# ---------------------------------------------------------------- 1. budget protection

def test_deep_reused_when_no_new_commits(repo):
    a, _ = audit(repo)
    repo.post(f"/api/audits/{a['id']}/deep")
    wait_for(repo, a["id"], {"complete"})
    b, _ = audit(repo, url="https://github.com/team/app?x")  # a fresh quick of the same commit
    db.update(b["id"], status="quick_ready", phase_deep="available", cached_from=None)
    deep_runs = len(repo.calls["deep"])
    r = repo.post(f"/api/audits/{b['id']}/deep").json()
    assert r["status"] == "complete" and r["reuse"]["deep"] and len(repo.calls["deep"]) == deep_runs


def test_deep_per_repo_and_daily_caps(repo, monkeypatch):
    monkeypatch.setattr(limits, "DEEP_PER_REPO_DAILY", 1)
    a, _ = audit(repo)
    assert repo.post(f"/api/audits/{a['id']}/deep").status_code == 202
    wait_for(repo, a["id"], {"complete"})
    repo.state.sha = "sha2"
    b, _ = audit(repo)
    r = repo.post(f"/api/audits/{b['id']}/deep")
    assert r.status_code == 429 and "daily maximum" in r.json()["detail"] and "quick result is ready" in r.json()["detail"]
    assert repo.post(f"/api/audits/{b['id']}/deep", headers=ADMIN).status_code == 202  # admin isn't capped

    monkeypatch.setattr(limits, "DEEP_PER_REPO_DAILY", 99)
    monkeypatch.setattr(limits, "DEEP_DAILY_CAP", 2)
    c, _ = audit(repo, url="https://github.com/team/other")
    r = repo.post(f"/api/audits/{c['id']}/deep")
    assert r.status_code == 429 and r.json()["detail"].startswith("Today's deep checks are used up")
    hits = repo.get("/api/admin/overview", headers=ADMIN).json()["limits"]
    assert {h["kind"] for h in hits["recent"]} >= {"deep_repo", "deep_daily"}
    assert hits["by_repo"][0]["key"] in ("team/app", "team/other")


def test_public_token_cap_blocks_deep_but_not_admin(repo, monkeypatch):
    monkeypatch.setattr(main.replay, "mode", lambda: "live")
    monkeypatch.setattr(main.POOL, "public_cap", 1000)
    monkeypatch.setattr(main.POOL, "public_used", 999)
    monkeypatch.setattr(main.POOL, "public_day", main.POOL.public_day or "x")
    main.POOL._roll_public()
    main.POOL.public_used = 999
    a, _ = audit(repo)
    r = repo.post(f"/api/audits/{a['id']}/deep")
    assert r.status_code == 429 and "AI budget" in r.json()["detail"]


def test_public_cap_in_pool_spares_the_reserve():
    pool = QuotaPool(["m"], reserve_pct=25, public_cap=10_000)
    assert pool.daily_ok("m", 5000)
    pool.record("m", 9000)                       # public traffic
    assert not pool.daily_ok("m", 5000) and pool.daily_ok("m", 5000, use_reserve=True)
    pool.record("m", 50_000, public=False)       # reserve traffic doesn't eat the public cap
    assert pool.public_used == 9000


def test_hackathon_repos_jump_the_deep_queue(repo):
    lane = jobs.Lane("deep", 45)
    lane.start = lambda: None
    lane._wake = asyncio.Event()
    lane.put("old1", (False, 0), priority=0)
    lane.put("old2", (False, 0), priority=0)
    lane.put("hack1", (False, 1), priority=1)
    lane.put("hack2", (False, 1), priority=1)
    assert [a for a, _ in lane.pending] == ["hack1", "hack2", "old1", "old2"]


# ---------------------------------------------------------------- 3. projects + progress

def test_projects_and_progress_with_fixed_checks(repo):
    a, _ = audit(repo)
    repo.state.sha, repo.state.score = "sha2", 68
    repo.state.checks = checks(demo_video="pass", cfo_ai_plan="pass")
    b, body = audit(repo)
    p = body["result"]["progress"]
    assert p["text"] == "+22 since your last check (46 → 68)" and p["delta"] == 22
    assert set(p["fixed"]) == {"demo video", "cfo ai plan"} and p["previous_audit_id"] == a["id"]
    proj = db.get_project("team/app")
    assert proj["audit_count"] == 2 and proj["latest_score"] == 68 and proj["best_score"] == 68
    assert proj["is_hackathon_repo"] == 1


def test_card_shows_positive_delta_only(repo, monkeypatch):
    seen = []
    monkeypatch.setattr(main, "render_card", lambda **kw: seen.append(kw) or b"png")
    audit(repo)
    repo.state.sha, repo.state.score = "sha2", 60
    b, _ = audit(repo)
    repo.get(f"/api/audits/{b['id']}/card.png")
    assert seen[-1]["delta"] == 14
    repo.state.sha, repo.state.score = "sha3", 50
    c, _ = audit(repo)
    repo.get(f"/api/audits/{c['id']}/card.png")
    assert seen[-1]["delta"] is None


def test_render_card_with_delta():
    from app.card import render_card
    png = render_card(repo="a/b", score=68, roast="r", site="x", delta=22)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------- 4. percentiles

def seed_cohort(n, *, hackathon=True, run_kind="real", start=0):
    for i in range(start, start + n):
        key = f"team/r{i}"
        result = {"checks_version": CHECKS_VERSION, "score": {"score": i * 5},
                  "checks": checks(inside=5 if hackathon else 0, demo_video="pass" if i < 5 else "fail")}
        db.create(f"c{i:011d}", f"https://github.com/{key}", key, f"s{i}", run_kind, status="quick_ready",
                  result=result)
        history.record(f"c{i:011d}", db.get(f"c{i:011d}"), result, deep=False)


def fresh_cohort():
    return history.Cohort(ttl_s=0)


def test_percentiles_hidden_below_15_repos(repo):
    seed_cohort(14)
    assert history.percentiles("team/me", {"score": {"score": 50}, "checks": checks()}, fresh_cohort()) is None


def test_percentiles_overall_and_per_check(repo):
    seed_cohort(20)  # scores 0..95; 5 of 20 have a demo under 3:00
    out = history.percentiles("team/me", {"score": {"score": 62}, "checks": checks(demo_video="pass")},
                              fresh_cohort())
    assert out["cohort_size"] == 20 and out["beats_pct"] == 65
    assert out["text"] == "Your score beats 65% of neatHack repos we've checked"
    demo = next(c for c in out["checks"] if c["check_id"] == "demo_video")
    assert demo["pct"] == 25 and demo["text"] == "Only 25% of teams have a demo video under 3:00. You're one of them ✅"
    assert "team/r" not in str(out)  # never other repos' names


def test_cohort_excludes_test_runs_removed_non_hackathon_and_our_repo(repo, monkeypatch):
    seed_cohort(10)
    for i in range(10, 13):
        key = f"team/x{i}"
        db.create(f"t{i:011d}", f"https://github.com/{key}", key, "s", "test", status="quick_ready",
                  result={"score": {"score": 1}, "checks": checks()})
        history.record(f"t{i:011d}", db.get(f"t{i:011d}"), {"score": {"score": 1}, "checks": checks()}, deep=False)
    db.create("own000000000", "https://github.com/DurgaPritam/neatHack-QBITS-", "durgapritam/neathack-qbits-",
              "s", "real", status="quick_ready", result={"score": {"score": 99}, "checks": checks()})
    history.record("own000000000", db.get("own000000000"), {"score": {"score": 99}, "checks": checks()}, deep=False)
    db.create("old000000000", "https://github.com/old/one", "old/one", "s", "real", status="quick_ready",
              result={"score": {"score": 5}, "checks": checks(inside=0)})
    history.record("old000000000", db.get("old000000000"), {"score": {"score": 5}, "checks": checks(inside=0)},
                   deep=False)
    db.set_hidden("c00000000000", True)
    assert fresh_cohort().stats()["size"] == 9


def test_cohort_is_cached(repo):
    clock = [0.0]
    cohort = history.Cohort(ttl_s=600, clock=lambda: clock[0])
    seed_cohort(3)
    assert cohort.stats()["size"] == 3
    seed_cohort(3, start=3)
    assert cohort.stats()["size"] == 3   # cached
    clock[0] = 601
    assert cohort.stats()["size"] == 6


def test_api_includes_percentiles_once_cohort_is_big_enough(repo, monkeypatch):
    seed_cohort(16)
    monkeypatch.setattr(history, "COHORT", fresh_cohort())
    a, body = audit(repo)
    assert body["percentiles"]["cohort_size"] >= 15


# ---------------------------------------------------------------- 5. admin

def test_admin_overview_requires_token_and_has_everything(repo):
    assert repo.get("/api/admin/overview").status_code == 401
    audit(repo)
    o = repo.get("/api/admin/overview", headers=ADMIN).json()
    for key in ("budget", "deep", "queue", "reuse", "limits", "projects", "recent_audits", "feedback", "metrics"):
        assert key in o
    assert o["deep"]["daily_cap"] == limits.DEEP_DAILY_CAP and o["projects"][0]["repo_key"] == "team/app"
    assert "public_tokens" in o["budget"]


def test_progress_compares_quick_with_quick_and_deep_with_deep():
    deep_prev = {"id": "p", "created_at": "t", "status": "complete",
                 "result": {"score": {"score": 68}, "quick_score": 61, "checks": []}}
    quick_now = {"phase": "quick", "score": {"score": 64}, "checks": []}
    assert history.progress(deep_prev, quick_now)["text"] == "+3 since your last check (61 → 64)"
    deep_now = {"phase": "complete", "mode": "full", "score": {"score": 70}, "checks": []}
    assert history.progress(deep_prev, deep_now)["text"] == "+2 since your last check (68 → 70)"
    old_row = {**deep_prev, "result": {"score": {"score": 68}, "checks": []}}  # before quick_score existed
    assert history.progress(old_row, quick_now) is None
    quick_prev = {"id": "q", "created_at": "t", "status": "quick_ready", "result": {"score": {"score": 50}}}
    assert history.progress(quick_prev, deep_now) is None  # no earlier deep check to compare with


def test_degraded_deep_result_is_not_reused(repo, monkeypatch):
    async def failing_deep(report, ctx, steps, use_reserve=False):
        steps.note("verify.llm_failed", "still no quota after 4 waits", status="failed")
        return {**report, "phase": "complete", "mode": "full", "score": {"score": 40},
                "verdict": {"source": "llm", "roast": "r"}, "steps": steps.to_list()}
    monkeypatch.setattr(jobs, "_run_deep", failing_deep)
    a, _ = audit(repo)
    repo.post(f"/api/audits/{a['id']}/deep")
    done = wait_for(repo, a["id"], {"complete"})
    assert done["result"]["deep_degraded"] is True
    assert db.find_deep_result("team/app", "sha1", CHECKS_VERSION) is None
    again = post(repo, "https://github.com/team/app").json()
    assert not (again.get("reuse") or {}).get("deep")  # the failed deep run isn't handed out


def test_old_degraded_rows_are_detected_from_steps(repo):
    db.create("old0degraded", "https://github.com/team/old", "team/old", "s9", "real", status="complete",
              steps=[{"name": "verify.llm_failed", "status": "failed"}],
              result={"checks_version": CHECKS_VERSION, "score": {"score": 1}})
    assert db.find_deep_result("team/old", "s9", CHECKS_VERSION) is None
    assert db.find_reusable("team/old", "s9", CHECKS_VERSION) is None
