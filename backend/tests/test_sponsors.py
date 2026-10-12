"""Sponsor Depth Scorecard: levels 0-4 from the checks only, conservative when unsure."""
from app import sponsors as S
from tests.test_api import client, post, wait_for  # noqa: F401  (fixture)


def rep(*checks, claims=()):
    return {"checks": list(checks), "agent": {"claims": [{"claim": c, "status": "verified"} for c in claims]}}


def chk(cid, status, evidence=(), detail="", data=None):
    return {"id": cid, "status": status, "evidence": list(evidence), "detail": detail, "data": data or {}}


def test_neatlogs_levels():
    assert S.neatlogs(rep())["level"] == 0
    assert S.neatlogs(rep(chk("neatlogs_sdk", "warn", ["mentions neatlogs"])))["level"] == 1
    walled = S.neatlogs(rep(chk("neatlogs_sdk", "pass", ["requirements.txt"]), chk("neatlogs_traces", "warn")))
    assert walled["level"] == 2 and "login" in walled["why"] and "screenshots" in walled["next_step"]
    shown = rep(chk("neatlogs_sdk", "pass"), chk("neatlogs_traces", "pass", ["docs/trace.png"]))
    assert S.neatlogs(shown)["level"] == 3
    # before/after numbers that are about something else don't count as neatlogs-driven
    assert S.neatlogs(rep(*shown["checks"], chk("before_after", "pass", ["Before 3 users after 9 users"])))["level"] == 3
    four = S.neatlogs(rep(*shown["checks"], chk("before_after", "pass", ["Before 40,086 tokens after 19,066 tokens"])))
    assert four["level"] == 4 and four["label"] == "used to improve" and "40,086 tokens" in four["evidence"][0]


def test_entire_levels():
    assert S.entire(rep(chk("entire_checkpoints", "unverified")))["level"] == 0
    assert S.entire(rep(chk("entire_checkpoints", "unverified", [".entire/settings.json"])))["level"] == 1
    link = "https://entire.io/gh/a/b/commit/" + "0" * 40
    two = S.entire(rep(chk("entire_checkpoints", "warn", data={"checkpoint_link": link})))
    assert two["level"] == 2 and link in two["next_step"]
    three = rep(chk("entire_checkpoints", "pass", data={"checkpoint_link": link}))
    assert S.entire(three)["level"] == 3 and S.entire(three)["evidence"] == [link]
    assert S.entire(rep(*three["checks"], claims=["Entire checkpoints show the switch to a two-speed audit"]))["level"] == 4
    # a claim that Entire is merely used is not "used to improve"
    assert S.entire(rep(*three["checks"], claims=["The project has Entire enabled, with checkpoints pushed"]))["level"] == 3


def test_cfo_levels():
    assert S.cfo(rep(chk("cfo_ai_plan", "fail")))["level"] == 0
    assert S.cfo(rep(chk("cfo_ai_plan", "warn", detail="no cfo.ai plan link (mentioned in text only)")))["level"] == 1
    two = S.cfo(rep(chk("cfo_ai_plan", "warn", ["https://cfo.ai/s/x"], data={"topics": ["pricing"]})))
    assert two["level"] == 2 and "cost, revenue, runway" in two["why"]
    three = rep(chk("cfo_ai_plan", "pass", ["https://cfo.ai/s/x"], data={"topics": ["pricing", "cost", "revenue", "runway"]}))
    assert S.cfo(three)["level"] == 3
    assert S.cfo(rep(*three["checks"], claims=["Measured AI cost moved break-even in the cfo.ai plan 9 months earlier"]))["level"] == 4
    assert S.cfo(rep(*three["checks"], claims=["The project includes a business plan built in cfo.ai."]))["level"] == 3
    assert S.cfo(rep(chk("cfo_ai_plan", "fail", ["https://cfo.ai/s/x"], detail="cfo.ai link is dead")))["level"] == 1


def test_scorecard_on_every_result_and_flag(client, monkeypatch):  # noqa: F811
    aid = post(client, "https://github.com/acme/demo").json()["id"]
    wait_for(client, aid, ("quick_ready",))
    card = client.get(f"/api/audits/{aid}").json()["sponsors"]
    assert [r["tool"] for r in card] == ["neatlogs", "Entire", "cfo.ai"] and all(r["next_step"] for r in card)
    monkeypatch.setenv("FEATURE_SPONSOR_SCORECARD", "0")
    assert client.get(f"/api/audits/{aid}").json()["sponsors"] is None
