"""Old audits with raw yt-dlp errors get today's friendly messages; nothing else changes."""
import json
import sqlite3

from app import migrate_friendly as M
from app.tools.video import FRIENDLY

RAW = ("[youtube] agGiWUpxkhg: Sign in to confirm you’re not a bot. Use --cookies-from-browser or "
       "--cookies for the authentication. See  https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-"
       "cookies-to-yt-dlp  for how to manually pass cookies.")
BOT = FRIENDLY["bot_check"].rstrip(".")


def old_audit():
    result = {
        "score": {"score": 54, "fix_candidates": [{"check_id": "demo_video",
                                                   "detail": f"video link live; duration unknown ({RAW})"}]},
        "videos": [{"url": "https://youtu.be/agGiWUpxkhg", "status": "unknown", "reason": RAW}],
        "checks": [{"id": "demo_video", "status": "unverified", "detail": f"video link live; duration unknown ({RAW})",
                    "data": {"duration_status": "unknown", "reason": RAW}},
                   {"id": "dead_links", "status": "pass", "detail": "33 links checked"}],
        "verdict": {"roast": "12 commits.", "fixes": [{"check_id": "demo_video",
                                                       "fix": f"We couldn't read the demo's length ({RAW})."}]},
        "steps": [{"name": "video.duration", "detail": f"unknown ({RAW[:120]}"}],
    }
    steps = [{"name": "video.duration", "status": "failed", "detail": f"unknown ({RAW[:120]}"}]
    return result, steps


def test_rewrite_replaces_every_raw_message():
    result, steps = old_audit()
    new, new_steps, changes = M.rewrite(result, steps)
    text = json.dumps(new) + json.dumps(new_steps)
    assert "Sign in to confirm" not in text and "cookies" not in text and "[youtube]" not in text
    assert new["videos"][0] == {"url": "https://youtu.be/agGiWUpxkhg", "status": "unknown",
                                "reason": FRIENDLY["bot_check"], "reason_code": "bot_check"}
    assert new["checks"][0]["detail"] == f"video link live; duration unknown ({BOT})"
    assert new["checks"][0]["data"]["reason_code"] == "bot_check"
    assert new["verdict"]["fixes"][0]["fix"] == f"We couldn't read the demo's length ({BOT})."
    assert new_steps[0]["detail"] == f"unknown ({BOT}"[:len(new_steps[0]["detail"])]
    assert new["score"]["score"] == 54 and new["checks"][1] == result["checks"][1]
    assert changes


def test_friendly_audits_are_left_alone():
    result = {"videos": [{"status": "unknown", "reason": FRIENDLY["timeout"], "reason_code": "timeout"}],
              "checks": [{"id": "demo_video", "detail": "x", "data": {"reason": FRIENDLY["timeout"]}}]}
    assert M.rewrite(result, [{"detail": "12 links, 0 dead"}])[2] == []


def test_run_backs_up_then_rewrites(tmp_path):
    db = tmp_path / "p.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE audits (id TEXT PRIMARY KEY, result TEXT, steps TEXT)")
    result, steps = old_audit()
    con.execute("INSERT INTO audits VALUES ('fc5068d87579', ?, ?)", (json.dumps(result), json.dumps(steps)))
    con.execute("INSERT INTO audits VALUES ('clean', ?, '[]')", (json.dumps({"checks": []}),))
    con.commit()
    con.close()

    assert [a for a, _ in M.run(db, apply=False)] == ["fc5068d87579"]
    assert "Sign in" in sqlite3.connect(db).execute("SELECT result FROM audits").fetchone()[0]  # dry run

    M.run(db, apply=True)
    backups = list(tmp_path.glob("p-before-friendly-*.db"))
    assert len(backups) == 1
    assert "Sign in" in sqlite3.connect(backups[0]).execute("SELECT result FROM audits").fetchone()[0]
    rows = dict(sqlite3.connect(db).execute("SELECT id, result || steps FROM audits").fetchall())
    assert "Sign in" not in rows["fc5068d87579"] and BOT in rows["fc5068d87579"]
    assert M.run(db, apply=False) == []  # idempotent
