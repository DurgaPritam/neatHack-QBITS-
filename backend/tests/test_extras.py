"""Demo script + judge panel: code owns structure, times and TODOs; the LLM only writes words."""
import asyncio
import json

from app import extras
from app.llm import LLM, QuotaPool
from app.steps import StepLog
from tests.fakes import FakeGroq, msg, server_error
from tests.test_api import client, post, wait_for  # noqa: F401  (fixture)

REPORT = json.load(open("fixtures/audits/openai__swarm.json"))   # no neatlogs, no Entire, no cfo.ai
GOOD = {**REPORT, "checks": [
    {"id": "neatlogs_sdk", "status": "pass", "detail": "in requirements.txt", "evidence": ["requirements.txt:3"]},
    {"id": "neatlogs_traces", "status": "pass", "detail": "2 screenshots", "evidence": ["https://app.neatlogs.com/t/1"]},
    {"id": "entire_checkpoints", "status": "pass", "detail": "3 trailers", "evidence": [],
     "data": {"checkpoint_link": "https://entire.io/gh/openai/swarm/commit/abc", "checkpoint_id": "01ABC"}},
    {"id": "cfo_ai_plan", "status": "pass", "detail": "plan linked", "evidence": ["https://cfo.ai/p/1"]},
    {"id": "before_after", "status": "pass", "detail": "numbers", "evidence": ["Before 37% after 100%"]},
    {"id": "demo_video", "status": "fail", "detail": "no video", "evidence": [], "data": {"duration_status": "no_video"}},
]}


def _llm(script):
    return LLM(StepLog(), client=FakeGroq(script), models=["m"], pool=QuotaPool(["m"]), sleep=lambda s: asyncio.sleep(0))


def run(coro):
    return asyncio.run(coro)


def test_template_script_is_3_minutes_covers_the_tools_and_marks_missing_evidence():
    s = run(extras.demo_script(REPORT, None))
    assert s["source"] == "template" and s["total"] == "3:00" and sum(x["seconds"] for x in s["scenes"]) == 180
    ids = [x["id"] for x in s["scenes"]]
    assert {"neatlogs", "entire", "cfo", "architecture", "result"} <= set(ids)
    todo = {x["id"] for x in s["scenes"] if x["todo"]}
    assert todo == {"neatlogs", "entire", "cfo", "result"}                    # swarm has none of them
    assert "TODO: no Entire checkpoint found" in s["text"] and s["todos"] == 4
    good = run(extras.demo_script(GOOD, None))
    assert good["todos"] == 0 and "https://entire.io/gh/openai/swarm/commit/abc (ID 01ABC)" in good["text"]
    assert "https://cfo.ai/p/1" in good["text"] and "https://app.neatlogs.com/t/1" in good["text"]


def test_llm_script_keeps_code_structure_drops_invented_links_and_cannot_hide_a_todo():
    scenes = [{"id": sid, "show": f"show {sid} https://cfo.ai/p/1", "say": f"say {sid}"} for sid, *_ in extras.SCENES]
    scenes[2]["show"] = "Our trace at https://evil.example/fake and 99.9% accuracy"    # invented link
    s = run(extras.demo_script({**GOOD, "checks": GOOD["checks"][:4] + GOOD["checks"][5:]}, _llm([msg({"scenes": scenes})])))
    assert s["source"] == "llm" and s["total_seconds"] == 180
    neat = next(x for x in s["scenes"] if x["id"] == "neatlogs")
    assert "evil.example" not in neat["show"] and "[link: TODO]" in neat["show"]
    result = next(x for x in s["scenes"] if x["id"] == "result")             # before/after removed: TODO wins
    assert result["todo"] and result["show"].startswith("TODO") and "say result" not in s["text"]


def test_llm_failure_falls_back_to_template():
    s = run(extras.demo_script(GOOD, _llm([server_error(), server_error(), server_error(), server_error()] * 3)))
    assert s["source"] == "template" and s["total"] == "3:00"


def test_judge_panel_personas_template_and_llm():
    p = run(extras.judge_panel(REPORT, None))
    assert [j["title"] for j in p["judges"]] == ["Observability judge", "Dev-workflow judge", "Business judge"]
    assert p["source"] == "template" and all(j["praise"] and j["fix"] for j in p["judges"])
    biz = p["judges"][2]["fix"]
    assert "demo" in biz.lower() or "cfo" in biz.lower()                     # a fix from its own area
    reply = {"judges": [{"id": "observability", "praise": "Traces at https://app.neatlogs.com/t/1 show real runs.",
                         "fix": "Add a failure trace, see https://made.up/x."},
                        {"id": "dev_workflow", "praise": "Checkpoints are linked.", "fix": "Link checkpoint 01ABC."},
                        {"id": "business", "praise": "The cfo.ai plan is there.", "fix": "Record the demo video."}]}
    p = run(extras.judge_panel(GOOD, _llm([msg(reply)])))
    assert p["source"] == "llm" and p["judges"][0]["title"] == "Observability judge"   # titles stay ours
    assert "https://app.neatlogs.com/t/1" in p["judges"][0]["praise"] and "made.up" not in p["judges"][0]["fix"]


def test_flags_default_on_and_switch_off(monkeypatch):
    assert extras.enabled("demo_script") and extras.enabled("judge_panel")
    monkeypatch.setenv("FEATURE_DEMO_SCRIPT", "0")
    assert not extras.enabled("demo_script")


def test_endpoints_template_in_replay_and_flag_off(client, monkeypatch):  # noqa: F811
    aid = post(client, "https://github.com/acme/demo").json()["id"]
    wait_for(client, aid, ("quick_ready",))
    monkeypatch.setattr("app.main.replay.mode", lambda: "replay")
    s = client.get(f"/api/audits/{aid}/demo-script").json()
    assert s["source"] == "template" and s["total"] == "3:00"
    p = client.get(f"/api/audits/{aid}/judge-panel").json()
    assert len(p["judges"]) == 3
    monkeypatch.setenv("FEATURE_JUDGE_PANEL", "off")
    assert client.get(f"/api/audits/{aid}/judge-panel").status_code == 404
    assert client.get(f"/api/audits/{aid}/card.png").status_code == 200        # other routes untouched
    assert client.get("/api/audits/nope/demo-script").status_code == 404


def test_endpoint_uses_llm_once_then_cache(client, monkeypatch):  # noqa: F811
    aid = post(client, "https://github.com/acme/demo").json()["id"]
    wait_for(client, aid, ("quick_ready",))
    calls = []

    async def fake(report, llm):
        calls.append(llm)
        return {"version": extras.EXTRAS_VERSION, "source": "llm", "judges": []}
    monkeypatch.setattr("app.main.replay.mode", lambda: "live")
    monkeypatch.setattr("app.main.public_budget_ok", lambda: True)
    monkeypatch.setattr(extras, "judge_panel", fake)
    assert client.get(f"/api/audits/{aid}/judge-panel").json()["source"] == "llm"
    assert client.get(f"/api/audits/{aid}/judge-panel").json()["source"] == "llm"
    assert len(calls) == 1 and calls[0] is not None                            # second one came from the cache
    monkeypatch.setattr("app.main.public_budget_ok", lambda: False)             # budget out: template, no LLM
    monkeypatch.setattr(extras, "judge_panel", lambda report, llm: asyncio.sleep(0, {"source": "template", "llm": llm}))
    aid2 = post(client, "https://github.com/acme/other").json()["id"]
    wait_for(client, aid2, ("quick_ready",))
    assert client.get(f"/api/audits/{aid2}/judge-panel").json() == {"source": "template", "llm": None}


def test_bare_links_are_checked_too():
    f = extras.facts(GOOD)
    out = extras._clean("See docs.entire.io/guide and cfo.ai/p/1 and app.neatlogs.com/t/1, also https://cfo.ai/p/1.", f)
    assert "docs.entire.io" not in out and out.count("[link: TODO]") == 1
    assert "cfo.ai/p/1 " in out and "app.neatlogs.com/t/1" in out and "https://cfo.ai/p/1." in out
    assert extras._clean("Version 3.11 of python, e.g. the 3:00 cut.", f) == "Version 3.11 of python, e.g. the 3:00 cut."
