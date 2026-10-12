"""Submission post, Evidence section and README badge: built only from what the checks found."""
from app import kit
from tests.test_api import client, post, wait_for  # noqa: F401  (fixture)

FULL = {
    "repo": {"full_name": "team/app", "description": "An agent that roasts hackathon repos"},
    "checks": [
        {"id": "neatlogs_sdk", "status": "pass", "evidence": ["requirements.txt:3"]},
        {"id": "neatlogs_traces", "status": "warn", "evidence": ["https://app.neatlogs.com/t/1"]},
        {"id": "entire_checkpoints", "status": "pass", "evidence": [],
         "data": {"checkpoint_link": "https://entire.io/gh/team/app/commit/abc", "checkpoint_id": "a1b2c3d4e5f6"}},
        {"id": "cfo_ai_plan", "status": "pass", "evidence": ["https://cfo.ai/p/x"]},
        {"id": "demo_video", "status": "pass", "evidence": ["https://youtu.be/v"],
         "data": {"duration_status": "known", "duration": "2:41"}},
        {"id": "before_after", "status": "pass", "evidence": ["Before 37.5% after 100%"]},
        {"id": "failure_recovery", "status": "pass", "evidence": ["EVIDENCE.md:40"]},
        {"id": "public_posts", "status": "pass", "evidence": ["https://x.com/a/status/1"]},
    ],
}
EMPTY = {"repo": {"full_name": "team/app"}, "checks": [
    {"id": "demo_video", "status": "fail", "evidence": [], "data": {"duration_status": "no_video"}},
    {"id": "cfo_ai_plan", "status": "fail", "evidence": ["cost"]}]}


def test_post_official_format_with_blanks():
    p = kit.submission_post(FULL)
    lines = p["text"].split("\n")
    assert [l.split(":")[0] for l in lines[:5]] == ["Team", "Name", "Project", "Repo", "Demo"] and lines[-1] == "#neatHack"
    assert lines[0] == "Team: [___]" and lines[1] == "Name: [___]" and p["blanks"] == 2
    assert "Repo: https://github.com/team/app" in p["text"] and "Demo: https://youtu.be/v" in p["text"]
    assert "An agent that roasts" in lines[2] and p["length"] <= 280 and not p["over"]
    assert kit.submission_post(EMPTY)["text"].count("[___]") == 3        # no demo: a blank, never a guess


def test_post_length_counts_links_as_23_and_warns():
    assert kit.x_length("see https://example.com/a/very/long/path/that/is/long") == len("see ") + 23
    long = {**FULL, "repo": {"full_name": "team/" + "x" * 280}}
    p = kit.submission_post(long)
    assert p["over"] and p["length"] > 280


def test_evidence_section_found_items_and_todos():
    md = kit.evidence_markdown(FULL, "https://pj/a/1")
    assert md.startswith("## Evidence") and "TODO" not in md
    assert "[a1b2c3d4e5f6](https://entire.io/gh/team/app/commit/abc)" in md
    assert "[demo](https://youtu.be/v) (2:41)" in md and "[plan](https://cfo.ai/p/x)" in md
    md = kit.evidence_markdown(EMPTY, "https://pj/a/1")
    assert md.count("⚠️ TODO") == 8 and "plan](cost" not in md and "`cost`" not in md  # stray words never become evidence


def test_badge_svg():
    svg = kit.badge_svg(73)
    assert svg.startswith("<svg") and "73/100" in svg and "#2fb344" in svg
    assert "not roasted" in kit.badge_svg(None)


def test_kit_and_badge_endpoints(client):  # noqa: F811
    aid = post(client, "https://github.com/acme/demo").json()["id"]
    wait_for(client, aid, ("quick_ready",))
    k = client.get(f"/api/audits/{aid}/kit").json()
    assert k["post"]["text"].endswith("#neatHack") and k["evidence_md"].startswith("## Evidence")
    assert k["badge"]["markdown"].startswith("[![PreJudge score](") and k["badge"]["markdown"].endswith(f"/a/{aid})")
    assert "/badge/acme/demo.svg" in k["badge"]["url"]
    b = client.get("/badge/acme/demo.svg")
    assert b.status_code == 200 and b.headers["content-type"].startswith("image/svg+xml") and "30/100" in b.text
    assert "not roasted" in client.get("/badge/acme/never.svg").text
    from app import db
    db.set_hidden(aid, True, "removed")
    assert "not roasted" in client.get("/badge/acme/demo.svg").text           # removed: no score shown
    assert client.get("/badge/acme/..%2Fx.svg").status_code in (400, 404)
