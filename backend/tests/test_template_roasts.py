"""Fact-only roasts: many templates per style, filled with the repo's most interesting facts."""
import pytest

from app.agent import roast as R
from app.scoring import compute_score


def check(id_, status, detail="", data=None):
    return {"id": id_, "title": id_, "status": status, "detail": detail, **({"data": data} if data else {})}


STALE = {  # an old project resubmitted: commits before the window, dead links, long demo
    "repo": {"full_name": "acme/old-agent", "pushed_at": "2025-03-11T10:00:00Z", "stars": 42},
    "files_seen": 120, "dependency_files": ["pyproject.toml"],
    "checks": [check("repo_public", "pass"), check("readme_exists", "pass", "README has 1490 words"),
               check("commits_in_window", "fail", "0 inside, 37 before start, 0 after close; active days: none"),
               check("dead_links", "fail", "3/33 links dead"),
               check("demo_video", "fail", "video is 12:46", {"duration_status": "too_long", "duration": "12:46"}),
               check("public_posts", "fail", "no social posts linked"), check("prompt_injection", "pass")],
}
FRESH = {  # built during the hackathon, nothing old, video length unknown
    "repo": {"full_name": "team/fresh", "pushed_at": "2026-10-11T10:00:00Z", "stars": 0},
    "files_seen": 64, "dependency_files": ["requirements.txt"],
    "checks": [check("repo_public", "pass"), check("readme_exists", "pass", "README has 400 words"),
               check("commits_in_window", "pass", "23 inside, 0 before start, 0 after close"),
               check("dead_links", "pass", "12 links checked"),
               check("demo_video", "unverified", "length unknown",
                     {"duration_status": "unknown", "not_scored": True}),
               check("cfo_ai_plan", "fail", "no cfo.ai link"), check("prompt_injection", "pass")],
}
REPORTS = [STALE, FRESH]


def test_at_least_25_templates_five_per_style():
    assert set(R.TEMPLATES) == set(R.STYLES)
    assert all(len(t) >= 5 for t in R.TEMPLATES.values())
    assert sum(len(t) for t in R.TEMPLATES.values()) >= 25
    for templates in R.TEMPLATES.values():
        for t in templates:
            assert R._fields(t) & {"stat", "date", "video"}, t  # every one carries a checkable fact


@pytest.mark.parametrize("report", REPORTS, ids=["stale", "fresh"])
def test_every_eligible_template_passes_the_roast_rules(report):
    score = compute_score(report["checks"])
    slots = R.roast_slots(report, score)
    facts = R.build_facts(report)
    checked = 0
    for style, templates in R.TEMPLATES.items():
        for t in templates:
            if R._fields(t) <= set(slots):
                text = t.format(**slots)
                assert not R.roast_problems(text, facts, [], report), (style, text)
                assert "{" not in text and "pyproject" not in text and "requirements" not in text
                checked += 1
    assert checked >= 15


def test_slots_pick_the_interesting_facts():
    score = compute_score(STALE["checks"])
    slots = R.roast_slots(STALE, score)
    assert slots["stat"] == "37 commits pushed before the hackathon even started"
    assert slots["video"] == "12:46" and slots["date"] == "11 Mar 2025"
    assert slots["miss"] == "a demo under 3:00"  # the biggest fix, worded with the real length
    fresh = R.roast_slots(FRESH, compute_score(FRESH["checks"]))
    assert fresh["stat"] == "23 commits inside the hackathon window"
    assert "video" not in fresh and "date" not in fresh  # unknown length, pushed during the window
    assert fresh["miss"] == "a cfo.ai business plan"


def test_unknown_video_length_is_never_joked_about():
    score = compute_score(FRESH["checks"])
    for style in R.STYLES:
        for name in ("team/a", "team/b", "team/c", "team/d"):
            assert "3:00" not in R.template_roast(style, FRESH, score, name)


def test_template_is_chosen_by_repo_name_hash():
    score = compute_score(STALE["checks"])
    a = R.template_roast("food critic", STALE, score, "acme/old-agent")
    assert a == R.template_roast("food critic", STALE, score, "ACME/old-agent")
    picks = {R.template_roast("food critic", STALE, score, f"team/repo{i}") for i in range(30)}
    assert len(picks) >= 4


def test_recent_roast_is_skipped():
    score = compute_score(STALE["checks"])
    first = R.template_roast("strict professor", STALE, score, "acme/old-agent")
    second = R.template_roast("strict professor", STALE, score, "acme/old-agent", recent=[first])
    assert second != first and not R.roast_problems(second, R.build_facts(STALE), [first], STALE)


def test_nothing_missing_uses_compliments():
    report = {**FRESH, "checks": [c for c in FRESH["checks"] if c["id"] != "cfo_ai_plan"]}
    score = {"score": 97, "fix_candidates": []}
    text = R.template_roast("Bollywood drama", report, score, "team/fresh")
    assert "97/100" in text and "23 commits" in text and "missing" not in text


def test_weak_repos_never_get_compliments():
    score = compute_score(STALE["checks"])
    assert score["score"] < R.COMPLIMENT_FROM and R.roast_slots(STALE, score)["miss"]
    for style in R.STYLES:
        for i in range(12):
            text = R.template_roast(style, STALE, score, f"team/r{i}")
            assert not any(t.format(**R.roast_slots(STALE, score)) == text
                           for t in R.TEMPLATES[style] if R._is_compliment(t)), text


def test_small_early_history_is_still_a_fact():
    report = {**FRESH, "checks": [c if c["id"] != "commits_in_window" else
                                  check("commits_in_window", "fail", "0 inside, 2 before start, 0 after close")
                                  for c in FRESH["checks"]]}
    slots = R.roast_slots(report, compute_score(report["checks"]))
    assert slots["stat"] == "2 commits, all pushed before the hackathon even started"
