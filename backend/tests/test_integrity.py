"""Integrity signals: each one flags the mismatch AND stays quiet on its innocent look-alike."""
import struct
import zlib

from app import integrity as I

IN, EARLY, LATE = 2109222474347446272, 2105598595691446272, 2109947250078646272          # X ids: Oct 11, Oct 1, Oct 13
D_IN, D_EARLY = 1558781204889600000, 1555157326233600000                                  # Discord ids: Oct 11, Oct 1


def png(w=1200, h=700, pad=20_000, seed=b""):
    raw = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h) + b"\x08\x02\x00\x00\x00"
    return raw + struct.pack(">I", zlib.crc32(b"x")) + seed + b"\x00" * pad


def test_x_and_discord_dates():
    assert I.snowflake_time(2109287438342582620, I.TWITTER_EPOCH_MS).isoformat().startswith("2026-10-11T14:18")
    ok = I.x_post_dates([f"https://x.com/me/status/{IN}", "https://x.com/me"])
    assert ok["status"] == "ok" and "1 are dated inside" in ok["reason"].replace("All 1", "1")
    early = I.x_post_dates([f"https://twitter.com/me/status/{EARLY}?s=20", f"https://x.com/me/status/{LATE}"])
    assert early["status"] == "look" and "before the start" in early["reason"] and "after the close" in early["reason"]
    assert "fake" not in str(early).lower() and early["fix"]
    assert I.x_post_dates(["https://x.com/neathack"])["status"] == "ok"                    # profile links: nothing to check
    assert I.discord_dates([f"https://discord.com/channels/1/2/{D_IN}"])["status"] == "ok"
    assert I.discord_dates([f"https://discord.com/channels/1/2/{D_EARLY}"])["status"] == "look"


def test_video_date_unknown_never_guessed():
    yt = "https://youtu.be/abc"
    assert I.video_dates([{"url": yt, "published_at": None}])["status"] == "unknown"
    assert I.video_dates([{"url": yt, "published_at": "2026-09-01T10:00:00Z"}])["status"] == "look"
    assert I.video_dates([{"url": yt, "published_at": "2026-10-12T10:00:00Z"}])["status"] == "ok"
    assert I.video_dates([{"url": "https://www.loom.com/share/x"}])["status"] == "ok"      # not YouTube: n/a


def test_links_point_to_this_repo():
    me = "Team/App"
    ok = I.links_this_repo(["https://entire.io/gh/team/app/commit/abc", "https://github.com/Team/App/blob/main/x.py",
                            "https://github.com/pallets/click"], me)
    assert ok["status"] == "ok"                                          # repo links to other projects are fine
    bad = I.links_this_repo(["https://entire.io/gh/someone/else/commit/abc"], me)
    assert bad["status"] == "look" and bad["evidence"] == ["https://entire.io/gh/someone/else/commit/abc"]
    assert I.foreign_entire_links({"signals": [bad]}) == {"https://entire.io/gh/someone/else/commit/abc"}


def test_checkpoints_real():
    cid = "01KXGTTNGCEACC83QZEJ5YAF0D"
    commits = [{"sha": "abc1234567890", "checkpoint": cid, "committed_at": "2026-10-11T10:00:00Z"}]
    assert I.checkpoints_real(f"Entire checkpoint {cid}", [cid], commits)["status"] == "ok"
    missing = I.checkpoints_real("Entire checkpoint 01ZZZZZZZZZZZZZZZZZZZZZZZZ", [cid], commits)
    assert missing["status"] == "look" and "aren't in this repo" in missing["reason"]
    old = [{"sha": "abc1234567890", "checkpoint": cid, "committed_at": "2026-09-01T10:00:00Z"}]
    assert I.checkpoints_real(f"Entire checkpoint {cid}", [cid], old)["status"] == "look"
    assert I.checkpoints_real("Entire checkpoint 01ZZZZZZZZZZZZZZZZZZZZZZZZ", [cid], commits, refs_more=True)["status"] == "unknown"
    assert I.checkpoints_real("No ids here", [], [])["status"] == "ok"


def test_push_times_rebase_vs_gap():
    commits = [{"sha": "aaaaaaaaaaaa", "committed_at": "2026-10-11T10:00:00Z"}]
    pushed_early = [{"type": "PushEvent", "created_at": "2026-10-05T10:00:00Z", "payload": {"commits": [{"sha": "aaaaaaaaaaaa1"}]}}]
    pushed_ok = [{"type": "PushEvent", "created_at": "2026-10-11T10:05:00Z", "payload": {"commits": [{"sha": "aaaaaaaaaaaa1"}]}}]
    look = I.push_times(commits, pushed_early)
    assert look["status"] == "look" and "rebased" in look["fix"]
    assert I.push_times(commits, pushed_ok)["status"] == "ok"
    assert I.push_times(commits, [])["status"] == "unknown"              # events API gap: couldn't check
    # newer payloads have head/before only: commits after `before` up to `head` were pushed together
    hist = [{"sha": "cccccccccccc", "committed_at": "2026-10-11T12:00:00Z"},
            {"sha": "bbbbbbbbbbbb", "committed_at": "2026-10-11T11:00:00Z"},
            {"sha": "aaaaaaaaaaaa", "committed_at": "2026-10-11T10:00:00Z"}]
    ev = [{"type": "PushEvent", "created_at": "2026-10-11T12:05:00Z",
           "payload": {"head": "cccccccccccc0", "before": "aaaaaaaaaaaa0", "commits": []}}]
    r = I.push_times(hist, ev)
    assert r["status"] == "ok" and r["checked"].startswith("2 of 3")
    backdated = [{"type": "PushEvent", "created_at": "2026-10-09T12:05:00Z",
                  "payload": {"head": "cccccccccccc0", "before": "aaaaaaaaaaaa0", "commits": []}}]
    assert I.push_times(hist, backdated)["status"] == "look"
    assert I.push_times(commits, None)["status"] == "unknown"


def test_code_dump_and_template_mention():
    stats = [{"sha": "big0000000000", "additions": 9000, "date": "2026-10-10T08:00:00Z"},
             {"sha": "small00000000", "additions": 500, "date": "2026-10-11T08:00:00Z"}]
    assert I.code_dump(stats, "")["status"] == "look"
    assert I.code_dump(stats, "We started from the Vite React template.")["status"] == "ok"
    even = [{"sha": f"c{i:012d}", "additions": 1000, "date": "2026-10-11T08:00:00Z"} for i in range(6)]
    assert I.code_dump(even, "")["status"] == "ok"
    assert I.code_dump([{"sha": "x" * 12, "additions": 300, "date": "2026-10-11T08:00:00Z"}], "")["status"] == "ok"  # tiny
    assert I.code_dump(None, "")["status"] == "unknown"


def test_dates_before_repo_created():
    commits = [{"sha": "aaaaaaaaaaaa", "committed_at": "2026-10-10T09:00:00Z"}]
    assert I.before_created(commits, "2026-10-10T12:00:00Z")["status"] == "look"
    assert I.before_created(commits, "2026-10-10T12:00:00Z", "History moved from our old repo (new repo for the event)")["status"] == "ok"
    assert I.before_created(commits, "2026-10-10T08:00:00Z")["status"] == "ok"
    assert I.before_created(None, "2026-10-10T08:00:00Z")["status"] == "unknown"


def test_screenshots():
    a, b = png(seed=b"a"), png(seed=b"b")
    assert I.screenshots([{"src": "docs/t1.png", "exists": True, "bytes": a}, {"src": "docs/t2.png", "exists": True, "bytes": b}])["status"] == "ok"
    reused = I.screenshots([{"src": "docs/t1.png", "exists": True, "bytes": a}, {"src": "docs/t2.png", "exists": True, "bytes": a}])
    assert reused["status"] == "look" and "same image" in reused["reason"]
    assert I.screenshots([{"src": "docs/t.png", "exists": True, "bytes": png(w=40, h=20)}])["status"] == "look"
    assert I.screenshots([{"src": "docs/t.png", "exists": True, "bytes": b"hello"}])["status"] == "look"
    assert I.screenshots([{"src": "docs/t.png", "exists": False, "bytes": None}])["status"] == "look"
    assert I.screenshots([{"src": "https://x/y.png", "exists": True, "bytes": None}])["status"] == "unknown"
    assert I.screenshots([])["status"] == "ok"


def test_before_after_math():
    good = "| Metric | Before | After | Change |\n|---|---|---|---|\n| Tokens | 40,086 | 10,145 | 75% fewer |\n| Time | 106 s | 36.7 s | 2.9× faster |\n"
    assert I.before_after_math(good)["status"] == "ok"
    bad = "| Metric | Before | After | Change |\n|---|---|---|---|\n| Tokens | 40,000 | 30,000 | 75% fewer |\n"
    r = I.before_after_math(bad)
    assert r["status"] == "look" and "is 25%" in r["reason"] and "says 75%" in r["reason"]
    rounding = "| Metric | Before | After | Change |\n|---|---|---|---|\n| Accuracy | 37.5% | 100% | 167% higher |\n"
    assert I.before_after_math(rounding)["status"] == "ok"
    assert I.before_after_math("| a | Before | After |\n|---|---|---|\n| x | 1/8 | 6/8 |\n")["status"] == "ok"  # nothing stated


def test_fingerprints_admin_only_similarity():
    base = " ".join(f"word{i}" for i in range(300))
    near = base.replace("word150", "changed")
    other = " ".join(f"other{i}" for i in range(300))
    assert I.similarity(I.fingerprint(base), I.fingerprint(near)) > 0.8
    assert I.similarity(I.fingerprint(base), I.fingerprint(other)) < 0.2
    assert I.fingerprint("too short") == []


def test_evaluate_never_scored_and_neutral():
    r = I.evaluate(readme="", urls=[f"https://x.com/me/status/{EARLY}"], full_name="a/b", created_at=None, commits=None,
                   ref_ids=None, refs_more=False, videos=[], events=None, stats=None, images=None)
    assert r["scored"] is False and r["counts"]["look"] == 1 and len(r["signals"]) == 10
    text = str(r).lower()
    for word in ("fake", "cheat", "fraud"):
        assert word not in text
