"""Integrity eval: deliberately faked fixtures and innocent look-alikes, each with the expected verdict.

    python -m evals.integrity        # prints the table, writes evals/results/<date>-integrity.json

A case passes when the signal under test gives exactly the expected status (ok / look / unknown).
"""
import json
import struct
import sys
import zlib
from datetime import datetime, timezone
from pathlib import Path

from app import integrity as I

HERE = Path(__file__).resolve().parent
ME = "team/app"
IN_X, EARLY_X = 2109222474347446272, 2105598595691446272


def _png(seed: bytes) -> bytes:
    head = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 1280, 720) + b"\x08\x02\x00\x00\x00"
    return head + struct.pack(">I", zlib.crc32(seed)) + seed + b"\x00" * 30_000


def _base(**kw) -> dict:
    d = dict(readme="", urls=[], full_name=ME, created_at="2026-10-10T07:05:00Z",
             commits=[{"sha": "aaaaaaaaaaaa", "committed_at": "2026-10-11T10:00:00Z"}], ref_ids=[], refs_more=False,
             videos=[], events=[], stats=[], images=[])
    d.update(kw)
    return d


TABLE = "| Metric | Before | After | Change |\n|---|---|---|---|\n"
CASES = [  # (name, kind, signal, inputs, expected)
    ("Backdated commit: dated in the window, pushed before it started", "faked", "push_times",
     _base(events=[{"type": "PushEvent", "created_at": "2026-10-05T09:00:00Z",
                    "payload": {"head": "aaaaaaaaaaaa", "before": "000000000000", "commits": []}}]), "look"),
    ("Rebased branch: old author dates, committed and pushed in the window", "innocent", "push_times",
     _base(commits=[{"sha": "aaaaaaaaaaaa", "authored_at": "2026-09-20T10:00:00Z", "committed_at": "2026-10-11T10:00:00Z"}],
           events=[{"type": "PushEvent", "created_at": "2026-10-11T10:02:00Z",
                    "payload": {"head": "aaaaaaaaaaaa", "before": "000000000000", "commits": []}}]), "ok"),
    ("Events API gap: no push events returned", "innocent", "push_times", _base(events=[]), "unknown"),
    ("Entire link to another team's repo", "faked", "links_this_repo",
     _base(urls=["https://entire.io/gh/other/project/commit/" + "1" * 40]), "look"),
    ("Entire + GitHub links to this repo (different case)", "innocent", "links_this_repo",
     _base(urls=["https://entire.io/gh/Team/App/commit/" + "1" * 40, "https://github.com/TEAM/app/blob/main/a.py"]), "ok"),
    ("Demo video published before the hackathon", "faked", "video_date",
     _base(videos=[{"url": "https://youtu.be/x", "published_at": "2026-08-30T12:00:00Z"}]), "look"),
    ("Demo video date unavailable (API quota)", "innocent", "video_date",
     _base(videos=[{"url": "https://youtu.be/x", "published_at": None}]), "unknown"),
    ("Same screenshot reused as two different traces", "faked", "screenshots",
     _base(images=[{"src": "docs/run1.png", "exists": True, "bytes": _png(b"1")},
                   {"src": "docs/run2.png", "exists": True, "bytes": _png(b"1")}]), "look"),
    ("Two distinct real screenshots", "innocent", "screenshots",
     _base(images=[{"src": "docs/run1.png", "exists": True, "bytes": _png(b"1")},
                   {"src": "docs/run2.png", "exists": True, "bytes": _png(b"2")}]), "ok"),
    ("Wrong percentage: 40,000 -> 30,000 called '75% fewer'", "faked", "before_after_math",
     _base(readme=TABLE + "| Tokens | 40,000 | 30,000 | 75% fewer |\n"), "look"),
    ("Rounded percentage: 106 s -> 36.7 s called '65% faster'", "innocent", "before_after_math",
     _base(readme=TABLE + "| Time | 106 s | 36.7 s | 65% faster |\n"), "ok"),
    ("Code dump: one commit adds 90% of the code", "faked", "code_dump",
     _base(stats=[{"sha": "big000000000", "additions": 18_000, "date": "2026-10-10T08:00:00Z"},
                  {"sha": "small0000000", "additions": 2_000, "date": "2026-10-11T08:00:00Z"}]), "look"),
    ("Template start mentioned in the README", "innocent", "code_dump",
     _base(readme="We started from the create-next-app template.",
           stats=[{"sha": "big000000000", "additions": 18_000, "date": "2026-10-10T08:00:00Z"},
                  {"sha": "small0000000", "additions": 2_000, "date": "2026-10-11T08:00:00Z"}]), "ok"),
    ("X post from before the hackathon", "faked", "x_post_dates",
     _base(urls=[f"https://x.com/team/status/{EARLY_X}"]), "look"),
    ("X post inside the window", "innocent", "x_post_dates", _base(urls=[f"https://x.com/team/status/{IN_X}"]), "ok"),
    ("Quoted checkpoint ID that isn't in the repo", "faked", "checkpoints_real",
     _base(readme="Entire checkpoint 01ZZZZZZZZZZZZZZZZZZZZZZZZ", ref_ids=["01KXGTTNGCEACC83QZEJ5YAF0D"]), "look"),
    ("Commits dated before the repo was created", "faked", "before_created",
     _base(created_at="2026-10-11T12:00:00Z"), "look"),
    ("History moved from an older repo (said in the README)", "innocent", "before_created",
     _base(created_at="2026-10-11T12:00:00Z", readme="We moved the history from our old repo into a new repo."), "ok"),
]


def run() -> dict:
    rows = []
    for name, kind, sid, inputs, expected in CASES:
        got = next(s for s in I.evaluate(**inputs)["signals"] if s["id"] == sid)
        rows.append({"case": name, "kind": kind, "signal": sid, "expected": expected, "got": got["status"],
                     "pass": got["status"] == expected, "reason": got["reason"]})
    faked = [r for r in rows if r["kind"] == "faked"]
    innocent = [r for r in rows if r["kind"] == "innocent"]
    return {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "cases": rows,
            "faked_caught": sum(r["pass"] for r in faked), "faked": len(faked),
            "innocent_cleared": sum(r["pass"] for r in innocent), "innocent": len(innocent)}


def main() -> None:
    r = run()
    for c in r["cases"]:
        print(f"{'PASS' if c['pass'] else 'FAIL'}  {c['kind']:8} {c['signal']:18} expected {c['expected']:7} got {c['got']:7}  {c['case']}")
    print(f"\nFaked fixtures flagged: {r['faked_caught']}/{r['faked']} · innocent look-alikes not flagged: "
          f"{r['innocent_cleared']}/{r['innocent']}")
    out = HERE / "results" / f"{r['date']}-integrity.json"
    out.write_text(json.dumps(r, indent=1))
    print(f"saved {out.relative_to(HERE.parent)}")
    sys.exit(0 if all(c["pass"] for c in r["cases"]) else 1)


if __name__ == "__main__":
    main()
