"""/api/transparency: aggregate live numbers vs the cfo.ai plan; never a repo name; cached 5 min."""
import copy
import json

from app import db, transparency
from tests.test_api import client  # noqa: F401  (fixture)

SWARM = json.load(open("fixtures/audits/openai__swarm.json"))


def add(aid, repo, result, cached_from=None, run_kind="real"):
    db.create(aid, f"https://github.com/{repo}", repo, None, run_kind, status="complete", phase_quick="done",
              phase_deep="done", steps=result["steps"], result=result)
    if cached_from:
        db._db().execute("UPDATE audits SET cached_from = ? WHERE id = ?", (cached_from, aid))
        db._db().commit()


def test_stats_plan_vs_actual_and_no_names(client):  # noqa: F811
    transparency.reset()
    quick_only = copy.deepcopy(SWARM)
    quick_only["usage"] = {"total_tokens": 4048, "calls": 2, "quick": SWARM["usage"]["quick"]}
    quick_only["steps"] = [s for s in SWARM["steps"] if not s["name"].endswith(".fallback")]
    add("aaaaaaaaaaa1", "secretteam/hidden-project", SWARM)            # quick + deep, with fallbacks
    add("aaaaaaaaaaa2", "otherteam/thing", quick_only)                  # quick only
    add("aaaaaaaaaaa3", "otherteam/thing", quick_only, cached_from="aaaaaaaaaaa2")   # reused: costs nothing
    add("aaaaaaaaaaa4", "tester/x", SWARM, run_kind="test")             # never counted
    r = client.get("/api/transparency")
    assert r.headers["cache-control"] == "public, max-age=300"
    s = r.json()
    assert s["audits"] == 3 and s["audits_that_ran"] == 2 and s["reused_results"] == 1 and s["unique_repos"] == 2
    assert s["quick"]["audits"] == 2 and s["deep"]["audits"] == 1 and s["quick"]["avg_tokens"] == 4048
    assert abs(s["quick"]["avg_cost_usd"] - 0.004845) < 1e-6 and s["fallback_rate"] == 0.5
    assert s["plan"]["cost_per_audit_usd"] == 0.0095 and s["actual"]["deep_share"] == 0.5
    assert "per audit vs plan $0.0095" in s["plan_vs_actual"] and "% " in s["plan_vs_actual"]
    assert s["links"]["cfo_ai"] == "https://cfo.ai/s/xBCsLLiMtconXUBf" and "entire.io/gh/" in s["links"]["entire"]
    body = json.dumps(s).lower()
    for name in ("secretteam", "hidden-project", "otherteam", "tester", "swarm"):
        assert name not in body


def test_cached_for_five_minutes(client, monkeypatch):  # noqa: F811
    transparency.reset()
    calls = []
    monkeypatch.setattr(transparency, "compute", lambda: calls.append(1) or {"n": len(calls)})
    assert transparency.get(now=1000)["n"] == 1 and transparency.get(now=1299)["n"] == 1
    assert transparency.get(now=1300)["n"] == 2
    transparency.reset()
    monkeypatch.setenv("FEATURE_TRANSPARENCY", "0")
    assert client.get("/api/transparency").status_code == 404
