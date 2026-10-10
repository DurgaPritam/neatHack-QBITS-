import asyncio

from app.agent.loop import fix_text
from app.tools import rubric
from app.tools.video import get_duration


def run(url, extractor):
    return asyncio.run(get_duration(url, extractor=extractor))


def test_known_duration():
    m = run("https://youtu.be/abc", lambda u: {"duration": 166.4, "title": "Demo"})
    assert m["status"] == "known" and m["duration_s"] == 166 and m["duration"] == "2:46"


def test_unknown_with_reason_never_guessed():
    def boom(u):
        raise RuntimeError("ERROR: [youtube] abc: Sign in to confirm you're not a bot")
    m = run("https://www.youtube.com/watch?v=abc", boom)
    assert m["status"] == "unknown" and m["duration_s"] is None
    assert m["reason"].startswith("[youtube] abc: Sign in")
    m2 = run("https://vimeo.com/1", lambda u: {"title": "no duration"})
    assert m2["status"] == "unknown" and "no duration" in m2["reason"]


def test_non_video_host_not_fetched():
    called = []
    m = run("http://169.254.169.254/latest", lambda u: called.append(u))
    assert m["status"] == "unknown" and called == []


LINK = [{"url": "https://youtu.be/abc", "kind": "video", "ok": True}]


def meta(**kw):
    base = {"url": "https://youtu.be/abc", "duration_s": None, "duration": None, "status": "unknown", "reason": None}
    return [{**base, **kw}]


def test_demo_check_statuses():
    ok = rubric.check_demo_video(LINK, meta(duration_s=150, duration="2:30", status="known"))
    long = rubric.check_demo_video(LINK, meta(duration_s=766, duration="12:46", status="known"))
    unk = rubric.check_demo_video(LINK, meta(reason="Private video"))
    assert ok["status"] == "pass" and "2:30" in ok["detail"]
    assert long["status"] == "fail" and "12:46" in long["detail"]
    assert unk["status"] == "unverified" and "Private video" in unk["detail"]
    assert unk["data"]["duration_status"] == "unknown"
    assert rubric.check_demo_video([])["status"] == "fail"


def test_fix_never_claims_too_long_when_duration_unknown():
    unk = rubric.check_demo_video(LINK, meta(reason="Private video"))
    cand = {"check_id": "demo_video", "title": "Demo video", "detail": unk["detail"]}
    text = fix_text(cand, "Your video is too long, shorten it to 3 minutes.", {"demo_video": unk})
    assert "too long" not in text.lower() and "Private video" in text
    long = rubric.check_demo_video(LINK, meta(duration_s=766, duration="12:46", status="known"))
    text2 = fix_text(cand, "Trim the 12:46 demo to under 3 minutes.", {"demo_video": long})
    assert text2 == "Trim the 12:46 demo to under 3 minutes."  # true, so the LLM wording stays
