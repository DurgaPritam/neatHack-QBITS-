import asyncio

from app import db
from app.agent import prompts
from app.agent import roast as R
from app.agent.loop import write_verdict
from app.llm import LLM, QuotaPool
from app.scoring import compute_score
from app.steps import StepLog
from tests.fakes import FakeGroq, msg

REPORT = {
    "repo": {"full_name": "acme/demo", "pushed_at": "2025-03-11T10:00:00Z", "stars": 42},
    "files_seen": 120, "dependency_files": ["backend/requirements.txt"],
    "checks": [
        {"id": "repo_public", "title": "Repo is public", "status": "pass", "detail": ""},
        {"id": "commits_in_window", "title": "Commits", "status": "fail",
         "detail": "0 inside, 37 before start, 0 after close; active days: none"},
        {"id": "dead_links", "title": "No dead links", "status": "fail", "detail": "3/33 links dead"},
        {"id": "demo_video", "title": "Demo video", "status": "unverified",
         "detail": "video link live; duration unknown (Private video)",
         "data": {"duration_status": "unknown", "reason": "Private video"}},
        {"id": "prompt_injection", "title": "inj", "status": "pass", "detail": ""},
    ],
}


def test_style_is_stable_and_spread():
    assert R.style_for("acme/demo") == R.style_for("ACME/demo") == R.style_for("acme/demo")
    styles = {R.style_for(f"team/repo{i}") for i in range(40)}
    assert styles == set(R.STYLES)


def test_facts_have_anchors_and_unknowns_are_marked():
    facts = R.build_facts(REPORT)
    text = " ".join(f["fact"] for f in facts)
    assert "37 before it started" in text and "3 of 33" in text
    assert "UNKNOWN" in text and "Private video" in text
    assert any("2025-03-11" in f["anchors"] for f in facts)


def test_banned_phrase_rejected():
    facts = R.build_facts(REPORT)
    p = R.roast_problems("37 commits before kickoff make this repo a museum exhibit.", facts, [], REPORT)
    assert any("banned" in x for x in p)


def test_roast_without_a_specific_fact_rejected():
    facts = R.build_facts(REPORT)
    assert R.roast_problems("This repo has big dreams and small evidence.", facts, [], REPORT)
    assert not R.roast_problems("37 commits landed before the starting whistle even blew.", facts, [], REPORT)
    assert not R.roast_problems("Three of 33 links lead nowhere, 3/33 to be exact.", facts, [], REPORT)


def test_number_anchor_needs_whole_number():
    facts = [{"fact": "x", "anchors": ["37"]}]
    assert R.roast_problems("It has 370 problems.", facts, [], {"checks": []})
    assert not R.roast_problems("It has 37 problems.", facts, [], {"checks": []})


def test_reused_joke_rejected():
    facts = R.build_facts(REPORT)
    old = "Thirty seven commits arrived before the party even started, fashionably early."
    p = R.roast_problems("Wow, 37 commits arrived before the party even started.", facts, [old], REPORT)
    assert any("reuses a joke" in x for x in p)


def test_unknown_video_length_cannot_be_called_too_long_or_dead():
    facts = R.build_facts(REPORT)
    p = R.roast_problems("37 early commits and a demo video that's too long to sit through.", facts, [], REPORT)
    assert any("too long" in x for x in p)
    p2 = R.roast_problems("37 early commits and a dead demo video link.", facts, [], REPORT)
    assert any("dead/broken" in x for x in p2)


def test_template_roast_follows_the_rules():
    facts = R.build_facts(REPORT)
    for style in R.STYLES:
        t = R.template_roast(style, facts, 20)
        assert not R.roast_problems(t, facts, [], REPORT), (style, t)


def _verdict(roast):
    return {"roast": roast, "fixes": [], "best_thing": "The repo is public and readable."}


def _llm(script):
    return LLM(StepLog(), client=FakeGroq(script), models=["m"], pool=QuotaPool(["m"]),
               sleep=lambda s: asyncio.sleep(0))


def test_write_verdict_retries_bad_roast_then_remembers_good_one(tmp_path):
    db.connect(tmp_path / "r.db")
    seen = []

    def script(kw):
        seen.append(kw["messages"][-1]["content"])
        if len(seen) == 1:
            return msg(_verdict("A real museum exhibit of a repo."))
        return msg(_verdict("37 commits before kickoff: the team trained harder than the judges."))

    llm = _llm(script)
    score = compute_score(REPORT["checks"])
    out, source = asyncio.run(write_verdict(llm, score, REPORT, []))
    assert source == "llm" and out["roast"].startswith("37 commits")
    assert "banned" in seen[1]  # retry prompt lists the problems
    assert "roast_rejected" in " ".join(s.name for s in llm.steps.steps)
    assert db.recent_roasts() == [out["roast"]]
    # the next verdict is told about recent roasts
    llm2 = _llm(lambda kw: (seen.append(kw["messages"][1]["content"]),
                            msg(_verdict("3/33 links dead, a strong opening act.")))[1])
    asyncio.run(write_verdict(llm2, score, REPORT, []))
    assert "37 commits before kickoff" in seen[-1] and "STYLE:" in seen[-1]


def test_write_verdict_falls_back_to_template_roast(tmp_path):
    db.connect(tmp_path / "r2.db")
    llm = _llm(lambda kw: msg(_verdict("Big dreams, small evidence, as always.")))
    out, source = asyncio.run(write_verdict(llm, compute_score(REPORT["checks"]), REPORT, []))
    assert not R.roast_problems(out["roast"], R.build_facts(REPORT), [], REPORT)
    assert "roast_template" in " ".join(s.name for s in llm.steps.steps)


def test_prompt_mentions_rules():
    assert "BANNED" in prompts.VERDICT_SYSTEM and "UNKNOWN" in prompts.VERDICT_SYSTEM


def test_rewrite_asks_for_roast_only():
    systems = []

    def script(kw):
        systems.append(kw["messages"][0]["content"])
        if len(systems) == 1:
            return msg(_verdict("Ladies and gentlemen, 37 commits before kickoff!"))
        return msg({"roast": "37 commits before kickoff: the warm-up lasted longer than the match."})

    llm = _llm(script)
    out, _ = asyncio.run(write_verdict(llm, compute_score(REPORT["checks"]), REPORT, []))
    assert systems[1] == prompts.ROAST_ONLY_SYSTEM
    assert out["roast"].startswith("37 commits before kickoff: the warm-up")


def test_template_roasts_are_not_remembered_and_vary():
    llm = _llm(lambda kw: msg(_verdict("Big dreams, small evidence, as always.")))
    asyncio.run(write_verdict(llm, compute_score(REPORT["checks"]), REPORT, []))
    assert db.recent_roasts() == []
    facts = R.build_facts(REPORT)
    variants = {R.template_roast("strict professor", facts, 20, variant=i) for i in range(6)}
    assert len(variants) == 6
    assert all(not R.roast_problems(v, facts, [], REPORT) for v in variants)
