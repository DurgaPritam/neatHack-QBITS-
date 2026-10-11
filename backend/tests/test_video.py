import asyncio
import json

import httpx

from app.agent.loop import fix_text
from app.public import public_steps
from app.scoring import compute_score
from app.tools import rubric
from app.tools.video import FRIENDLY, get_duration, parse_iso_duration, youtube_id

BOT = "ERROR: [youtube] agGiWUpxkhg: Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies"


def run(url, extractor, transport=None):
    return asyncio.run(get_duration(url, extractor=extractor, transport=transport))


def boom(msg):
    def f(url):
        raise RuntimeError(msg)
    return f


def yt_api(status=200, body=None, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body if body is not None else {})
    return httpx.MockTransport(handler)


def test_known_duration_via_yt_dlp():
    m = run("https://youtu.be/abcdefghijk", lambda u: {"duration": 166.4, "title": "Demo"})
    assert m["status"] == "known" and m["duration_s"] == 166 and m["duration"] == "2:46" and m["source"] == "yt_dlp"


def test_raw_yt_dlp_errors_become_friendly_reasons():
    m = run("https://www.youtube.com/watch?v=agGiWUpxkhg", boom(BOT))
    assert m["status"] == "unknown" and m["duration_s"] is None and m["reason_code"] == "bot_check"
    assert m["reason"] == "YouTube didn't let us read the video length automatically."
    assert "cookies" not in json.dumps(m) and "agGiWUpxkhg:" not in json.dumps(m)
    assert run("https://vimeo.com/1", boom("ERROR: Private video"))["reason_code"] == "private"
    assert run("https://vimeo.com/1", boom("ERROR: Video unavailable"))["reason_code"] == "unavailable"
    assert run("https://vimeo.com/1", boom("weird internal thing"))["reason"] == FRIENDLY["error"]
    assert run("https://vimeo.com/1", lambda u: {"title": "no duration"})["reason_code"] == "no_duration"


def test_youtube_data_api_first(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "AIzaTESTKEY")
    seen, called = [], []
    body = {"items": [{"contentDetails": {"duration": "PT2M45S"}, "snippet": {"title": "PreJudge demo"}}]}
    m = run("https://youtu.be/agGiWUpxkhg", lambda u: called.append(u), yt_api(body=body, seen=seen))
    assert m["status"] == "known" and m["duration_s"] == 165 and m["source"] == "youtube_api" and called == []
    q = seen[0].url.params
    assert q["id"] == "agGiWUpxkhg" and q["part"] == "contentDetails,snippet" and q["key"] == "AIzaTESTKEY"
    assert "AIzaTESTKEY" not in json.dumps(m)


def test_youtube_api_no_items_means_not_public(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "AIzaTESTKEY")
    called = []
    m = run("https://www.youtube.com/watch?v=agGiWUpxkhg", lambda u: called.append(u), yt_api(body={"items": []}))
    assert m["reason_code"] == "not_found" and called == []  # a definite answer: don't ask yt-dlp


def test_youtube_api_failure_falls_back_to_yt_dlp_then_unknown(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "AIzaTESTKEY")
    quota = yt_api(403, {"error": {"errors": [{"reason": "quotaExceeded"}]}})
    m = run("https://youtu.be/agGiWUpxkhg", lambda u: {"duration": 120}, quota)
    assert m["status"] == "known" and m["source"] == "yt_dlp"
    m = run("https://youtu.be/agGiWUpxkhg", boom(BOT), quota)
    assert m["status"] == "unknown" and m["reason_code"] == "bot_check" and "quota" not in json.dumps(m)


def test_no_key_skips_the_api(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    seen = []
    m = run("https://youtu.be/agGiWUpxkhg", lambda u: {"duration": 90}, yt_api(seen=seen))
    assert m["source"] == "yt_dlp" and seen == []


def test_youtube_ids_and_iso_durations():
    for url in ("https://youtu.be/agGiWUpxkhg?t=3", "https://www.youtube.com/watch?v=agGiWUpxkhg&list=x",
                "https://youtube.com/shorts/agGiWUpxkhg", "https://www.youtube.com/embed/agGiWUpxkhg",
                "https://m.youtube.com/live/agGiWUpxkhg"):
        assert youtube_id(url) == "agGiWUpxkhg", url
    assert youtube_id("https://www.youtube.com/@channel") is None and youtube_id("https://vimeo.com/1") is None
    assert parse_iso_duration("PT2M45S") == 165 and parse_iso_duration("PT1H2S") == 3602
    assert parse_iso_duration("P0D") is None and parse_iso_duration("junk") is None


def test_non_video_host_not_fetched():
    called = []
    m = run("http://169.254.169.254/latest", lambda u: called.append(u))
    assert m["status"] == "unknown" and called == []


LINK = [{"url": "https://youtu.be/abc", "kind": "video", "ok": True}]


def meta(**kw):
    base = {"url": "https://youtu.be/abc", "duration_s": None, "duration": None, "status": "unknown",
            "reason_code": None, "reason": None}
    return [{**base, **kw}]


BOT_META = meta(reason_code="bot_check", reason=FRIENDLY["bot_check"])


def test_demo_check_statuses():
    ok = rubric.check_demo_video(LINK, meta(duration_s=150, duration="2:30", status="known"))
    long = rubric.check_demo_video(LINK, meta(duration_s=766, duration="12:46", status="known"))
    assert ok["status"] == "pass" and "2:30" in ok["detail"]
    assert long["status"] == "fail" and "12:46" in long["detail"]
    assert rubric.check_demo_video([])["status"] == "fail"


def test_unknown_length_is_not_scored_and_gives_advice():
    unk = rubric.check_demo_video(LINK, BOT_META)
    assert unk["status"] == "unverified" and unk["data"]["not_scored"]
    assert "YouTube didn't let us read the video length automatically." in unk["detail"]
    assert unk["data"]["advice"] == ("Make sure the video is public and mention its length (e.g. 'Demo: 2:45') "
                                     "in your README.")


def test_self_reported_length():
    for readme in ("## Demo\nDemo: 2:45\n", "Watch the 2 min 30 s video walkthrough", "[Demo video (2:59)](x)"):
        c = rubric.check_demo_video(LINK, BOT_META, readme)
        assert c["status"] == "pass" and "self-reported" in c["detail"], readme
        assert c["data"]["duration_status"] == "self_reported"
    over = rubric.check_demo_video(LINK, BOT_META, "Demo video: 4:10")
    assert over["status"] == "fail" and "4:10" in over["detail"] and "self-reported" in over["detail"]
    # clock times and lines that aren't about the video don't count
    for readme in ("Demo day starts 10:00 IST", "Built in 2:45 hours\nNo video yet"):
        assert rubric.check_demo_video(LINK, BOT_META, readme)["status"] == "unverified", readme


def test_private_or_removed_video_fails():
    c = rubric.check_demo_video(LINK, meta(reason_code="not_found", reason=FRIENDLY["not_found"]))
    assert c["status"] == "fail" and "judges can't watch" in c["detail"] and c["data"]["advice"]


def test_unknown_demo_doesnt_cost_points():
    ids = ["before_after", "failure_recovery", "neatlogs_sdk", "neatlogs_traces", "entire_checkpoints",
           "cfo_ai_plan", "commits_in_window", "public_posts", "readme_exists", "dead_links"]
    base = [{"id": i, "title": i, "status": "pass", "detail": ""} for i in ["repo_public", "prompt_injection"] + ids]
    est = {"agent_quality": {"score": 10, "evidence": ["a"]}, "usefulness": {"score": 10, "evidence": ["b"]}}
    with_video = compute_score(base + [{"id": "demo_video", "title": "d", "status": "pass", "detail": ""}], estimates=est)
    unknown = compute_score(base + [rubric.check_demo_video(LINK, BOT_META)], estimates=est)
    missing = compute_score(base + [rubric.check_demo_video([])], estimates=est)
    others = sum(c["points"] for c in unknown["categories"])            # every other category, same credit
    assert unknown["scored_max"] == 80 and abs(unknown["score"] - others / 80 * 100) <= 1
    assert abs(missing["score"] - others) <= 1 and unknown["score"] >= with_video["score"] - 1
    cat = next(c for c in unknown["categories"] if c["id"] == "demo_video")
    assert cat["not_scored"] and cat["max_points"] == 0
    assert all(f["check_id"] != "demo_video" for f in unknown["fix_candidates"])


def test_fix_never_claims_too_long_or_shows_raw_errors():
    gone = rubric.check_demo_video(LINK, meta(reason_code="private", reason=FRIENDLY["private"]))
    cand = {"check_id": "demo_video", "title": "Demo video", "detail": gone["detail"]}
    text = fix_text(cand, "Your video is too long, shorten it to 3 minutes.", {"demo_video": gone})
    assert "too long" not in text.lower() and "public" in text
    long = rubric.check_demo_video(LINK, meta(duration_s=766, duration="12:46", status="known"))
    text2 = fix_text(cand, "Trim the 12:46 demo to under 3 minutes.", {"demo_video": long})
    assert text2 == "Trim the 12:46 demo to under 3 minutes."  # true, so the LLM wording stays


def test_public_steps_hide_raw_errors():
    steps = [
        {"name": "llm.verify", "status": "failed", "error_kind": "rate_limited",
         "detail": "qwen/qwen3.8-27b: Error code: 429 - {'error': {'message': 'Rate limit reached'}}"},
        {"name": "github.get_tree", "status": "failed", "error_kind": "KeyError", "detail": "KeyError: 'tree'"},
        {"name": "quick.crashed", "status": "failed", "error_kind": None, "detail": "TimeoutError: boom"},
        {"name": "video.duration", "status": "failed", "error_kind": "duration_unknown",
         "detail": FRIENDLY["bot_check"]},
        {"name": "quick_verdict.roast_rejected", "status": "failed", "error_kind": None,
         "detail": "reuses a joke from a recent roast"},
        {"name": "github.get_repo", "status": "ok", "error_kind": None, "detail": "default branch main"},
    ]
    out = public_steps(steps)
    text = json.dumps(out)
    assert "Error code" not in text and "KeyError" not in text and "TimeoutError" not in text
    assert out[0]["detail"].startswith("Hit a rate limit") and out[3]["detail"] == FRIENDLY["bot_check"]
    assert out[4]["detail"] == "reuses a joke from a recent roast" and out[5] == steps[5]
