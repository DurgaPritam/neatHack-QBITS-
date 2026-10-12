"""Glass box: steps with time, tokens and list-price cost, retries and fallbacks; nothing secret leaves."""
import json

from app import costs
from tests.test_api import client, post, wait_for  # noqa: F401  (fixture)

SWARM = json.load(open("fixtures/audits/openai__swarm.json"))


def test_costs_match_the_plan_basis():
    # qwen at $0.80 / $4.00 per M: 3,546 in + 502 out = $0.004845 (the plan's ~$0.005 quick audit)
    assert abs(costs.usage_cost(SWARM["usage"]["quick"]) - 0.004845) < 1e-6
    assert costs.step_cost("openai/gpt-oss-20b", 1_000_000) < costs.step_cost("qwen/qwen3.8-27b", 1_000_000)


def test_glass_box_from_stored_steps():
    g = costs.glass_box(SWARM["steps"], SWARM["usage"], SWARM["timing_ms"])
    t = g["totals"]
    assert t["tokens"] == 14193 and t["fallbacks"] == 2 and t["quota_waits"] == 2 and t["retries"] >= 2
    assert t["ms"] == 36731 and g["traced_with"] == "neatlogs" and set(g["phases"]) == {"quick", "deep"}
    llm = [s for s in g["steps"] if s["tokens"]]
    assert all(s["cost_usd"] > 0 and s["model"] for s in llm)
    fb = [s for s in g["steps"] if s["kind"] == "fallback"]
    assert fb[0]["to_model"] == "openai/gpt-oss-120b"


def test_nothing_secret_or_raw_leaves():
    steps = [{"name": "llm.claims", "status": "failed", "error_kind": "rate_limited", "duration_ms": 140,
              "detail": "Error code: 429 - {'error': {'message': 'Rate limit ... org_01abc', 'type': 'tokens'}}",
              "data": {"model": "qwen/qwen3.8-27b", "est_tokens": 3880, "scheduled": "5 tokens left",
                       "prompt": "SECRET README TEXT", "ip": "10.0.0.1", "api_key": "gsk_xxx"}},
             {"name": "github.get_repo", "status": "failed", "error_kind": "KeyError", "duration_ms": 3,
              "detail": "KeyError: 'token ghp_secret'", "data": {}}]
    g = json.dumps(costs.glass_box(steps, {}, {}))
    for bad in ("org_01abc", "SECRET README", "10.0.0.1", "gsk_", "ghp_", "Error code", "KeyError", "scheduled"):
        assert bad not in g, bad


def test_glass_box_in_the_api_and_flag(client, monkeypatch):  # noqa: F811
    aid = post(client, "https://github.com/acme/demo").json()["id"]
    wait_for(client, aid, ("quick_ready",))
    g = client.get(f"/api/audits/{aid}").json()["glass_box"]
    assert g["steps"] and g["traced_with"] == "neatlogs"
    monkeypatch.setenv("FEATURE_GLASS_BOX", "off")
    assert client.get(f"/api/audits/{aid}").json()["glass_box"] is None
