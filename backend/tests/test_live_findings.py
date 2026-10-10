"""Regressions for problems found in live runs on swarm / smolagents / open_deep_research."""
import pytest

from app.agent import prompts
from app.agent import roast as R
from app.agent.loop import _match_results
from app.agent.schemas import ClaimList, VerifyResult, parse_json
from tests.test_agent import CLEAN_README, HONEST, audit, router
from tests.fakes import msg


def test_quoting_a_fact_is_not_reusing_a_joke():
    facts = [{"fact": "0 commits inside the hackathon window, 29 before it started", "anchors": ["29"]}]
    old = "Folks, 0 commits inside the hackathon window, what a quiet stadium tonight."
    new = "Somebody check the tape: 0 commits inside the hackathon window and 29 before kickoff."
    assert R.roast_problems(new, facts, [old], {"checks": []}) == []
    joke = "Folks, what a quiet stadium tonight, 29 times over."
    assert R.roast_problems(joke, facts, [old], {"checks": []})


@pytest.mark.parametrize("raw,cat", [("cli", "usefulness"), ("Integrations", "tools"), ("LLM support", "agent"),
                                     ("demo", "demo_video"), ("tools", "tools"), (None, "usefulness")])
def test_free_form_categories_are_mapped(raw, cat):
    c = ClaimList.model_validate({"claims": [{"id": 1, "text": "does a thing", "category": raw}]})
    assert c.claims[0].category == cat and c.claims[0].id == "1"


def test_missing_claims_key_is_an_error_not_an_empty_list():
    with pytest.raises(ValueError):
        parse_json('{"claim": [{"id": "c1", "text": "x y z"}]}', ClaimList)
    with pytest.raises(ValueError):
        parse_json('{"result": []}', VerifyResult)


def test_result_ids_are_matched_loosely():
    claims = ClaimList.model_validate({"claims": [{"id": "c1", "text": "aaa"}, {"id": "c2", "text": "bbb"}]})
    v = VerifyResult.model_validate({"results": [{"claim_id": "2", "status": "verified"},
                                                 {"claim_id": 1, "status": "contradicted"}]})
    m = _match_results(claims, v)
    assert m["c1"].status == "contradicted" and m["c2"].status == "verified"
    by_order = VerifyResult.model_validate({"results": [{"claim_id": "x", "status": "verified"},
                                                        {"claim_id": "y", "status": "unverified"}]})
    assert _match_results(claims, by_order)["c1"].status == "verified"


def test_final_answer_prompt_has_no_tools():
    assert "search_repo" not in prompts.VERIFY_FINAL_SYSTEM and "NO tools" in prompts.VERIFY_FINAL_SYSTEM


def test_empty_claims_from_long_readme_are_retried():
    calls = {"n": 0}
    base = router(HONEST)
    long_readme = CLEAN_README + ("More details about features and integrations. " * 60)

    def script(kw):
        if kw["messages"][0]["content"] == prompts.CLAIMS_SYSTEM:
            calls["n"] += 1
            if calls["n"] == 1:
                return msg({"claims": [], "injection_attempts": []})
        return base(kw)

    r, _ = audit(long_readme, script)
    assert calls["n"] == 2 and len(r["agent"]["claims"]) == 2
    assert "claims.empty_retry" in [s["name"] for s in r["steps"]]
