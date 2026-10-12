"""Ari prompt helper: README numbers in, [___] for the rest, no invented numbers, one LLM call max."""
import asyncio

from app import ari
from app.llm import LLM, QuotaPool
from app.steps import StepLog
from tests.fakes import FakeGroq, msg, server_error
from tests.test_api import client, post, wait_for  # noqa: F401  (fixture)

README = """# Shipr
Ship faster.
## Pricing
- Pro: $19/month per seat, Team: $99/month
- Each run costs about $0.004 in LLM tokens (2,600 tokens)
Hosting is $20/mo on one VM.
We have 140 users on the waitlist.
Install: pip install shipr==2.1
"""
REPORT = {"repo_url": "https://github.com/team/shipr", "repo": {"full_name": "team/shipr", "description": "Ship faster"}}


def _llm(script):
    return LLM(StepLog(), client=FakeGroq(script), models=["m"], pool=QuotaPool(["m"]), sleep=lambda s: asyncio.sleep(0))


def test_snippets_only_numbers_about_money_and_usage():
    s = ari.number_snippets(README)
    assert any("$19/month" in x for x in s) and any("$0.004" in x for x in s) and any("140 users" in x for x in s)
    assert not any("pip install" in x for x in s)


def test_template_fills_found_numbers_and_blanks_the_rest():
    r = asyncio.run(ari.ari_prompt(REPORT, None, readme=README))
    p = r["prompt"]
    assert r["source"] == "template" and "$19/month" in p and "Hosting is $20/mo" in p
    assert "Starting cash / funding: [___]" in p and r["blanks"] >= 1
    assert "export it from cfo.ai" in p and "put that link in the README" in p
    empty = asyncio.run(ari.ari_prompt(REPORT, None, readme="# Nothing here"))
    assert empty["numbers_found"] == [] and empty["blanks"] == len(ari.FIELDS) and "[___]" in empty["prompt"]


def test_llm_output_cannot_invent_numbers():
    out = {"prompt": "Shipr: Pro at $19/month, Team $99/month, $0.004 per run, hosting $20/mo, "
                     "and we expect 5,000 users and $250k ARR with 40% margin."}
    r = asyncio.run(ari.ari_prompt(REPORT, _llm([msg(out)]), readme=README))
    p = r["prompt"]
    assert r["source"] == "llm" and "$19/month" in p and "$0.004" in p and "$20/mo" in p
    assert "5,000 users" not in p and "$250k" not in p and "40%" not in p and p.count("[___]") == 3
    assert p.endswith(ari.REMINDER)


def test_llm_failure_falls_back_to_template():
    r = asyncio.run(ari.ari_prompt(REPORT, _llm([server_error()] * 12), readme=README))
    assert r["source"] == "template" and "$19/month" in r["prompt"]


def test_endpoint_and_flag(client, monkeypatch):  # noqa: F811
    aid = post(client, "https://github.com/acme/demo").json()["id"]
    wait_for(client, aid, ("quick_ready",))

    async def readme(url):
        return README
    monkeypatch.setattr(ari, "fetch_readme", readme)
    monkeypatch.setattr("app.main.replay.mode", lambda: "replay")
    r = client.get(f"/api/audits/{aid}/ari-prompt").json()
    assert r["source"] == "template" and "$19/month" in r["prompt"]
    assert client.get(f"/api/audits/{aid}").json()["features"]["ari_prompt"] is True
    monkeypatch.setenv("FEATURE_ARI_PROMPT", "0")
    assert client.get(f"/api/audits/{aid}/ari-prompt").status_code == 404
