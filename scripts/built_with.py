#!/usr/bin/env python3
"""Write frontend/public/built-with.json: our build story from git, Entire and EVIDENCE.md.

Only pushed commits (origin/main) are used, so every GitHub and entire.io link resolves.
Run by scripts/deploy.sh before the frontend build:  python3 scripts/built_with.py [--ref origin/main]
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "DurgaPritam/neatHack-QBITS-"
GH = f"https://github.com/{REPO}/commit/"
ENTIRE = f"https://entire.io/gh/{REPO}/commit/"
WINDOW = ("2026-10-10T07:00:00+00:00", "2026-10-12T18:25:00+00:00")
_SHA_LINK = re.compile(r"github\.com/[^/]+/[^/]+/commit/([0-9a-f]{7,40})")
_MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout


def commits(ref: str) -> list[dict]:
    out = []
    fmt = "%H%x1f%cI%x1f%s%x1f%(trailers:key=Entire-Checkpoint,valueonly,separator=%x2C)%x1e"
    for rec in git("log", ref, f"--format={fmt}").split("\x1e"):
        parts = rec.strip("\n").split("\x1f")
        if len(parts) < 4:
            continue
        sha, date, subject, cps = parts
        out.append({"sha": sha, "date": date, "subject": subject,
                    "checkpoints": [c.strip() for c in cps.split(",") if c.strip()]})
    return out


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _plain(md: str) -> str:
    return " ".join(_MD_LINK.sub(lambda m: m.group(1), md).replace("`", "").replace("**", "").split())


def improvements(evidence: str, by_prefix) -> list[dict]:
    """Rows of the 'Before/after improvements' table, each linked to its commit and checkpoint."""
    sec = evidence.split("## 4. Before/after improvements", 1)
    if len(sec) < 2:
        return []
    rows, last_links = [], []
    for line in sec[1].split("\n###", 1)[0].splitlines():
        if not line.startswith("|") or line.startswith("|---") or line.startswith("| Improvement"):
            continue
        c = _cells(line)
        if len(c) < 4:
            continue
        shas = _SHA_LINK.findall(c[3])
        found = [x for x in (by_prefix(s) for s in shas) if x]
        if c[3].strip().lower() == "same":
            found = last_links
        last_links = found
        rows.append({"improvement": _plain(c[0]), "before": _plain(c[1]), "after": _plain(c[2]),
                     "commits": [{"sha": x["sha"][:7], "url": GH + x["sha"], "subject": x["subject"],
                                  "checkpoint": (x["checkpoints"] or [None])[0],
                                  "checkpoint_url": ENTIRE + x["sha"] if x["checkpoints"] else None} for x in found]})
    return rows


def build(ref: str = "origin/main") -> dict:
    cs = commits(ref)
    by_full = {c["sha"]: c for c in cs}
    by_prefix = lambda p: next((c for s, c in by_full.items() if s.startswith(p)), None)  # noqa: E731
    tagged = [c for c in cs if c["checkpoints"]]
    in_window = [c for c in cs if WINDOW[0] <= datetime.fromisoformat(c["date"]).astimezone(timezone.utc).isoformat() <= WINDOW[1]]
    refs = git("for-each-ref", "--format=%(refname)", "refs/entire/checkpoints").split()
    evidence = (ROOT / "EVIDENCE.md").read_text()
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": f"https://github.com/{REPO}",
        "entire_project": f"https://entire.io/gh/{REPO}",
        "commits": len(cs), "commits_in_window": len(in_window),
        "first_commit": cs[-1]["date"] if cs else None, "last_commit": cs[0]["date"] if cs else None,
        "checkpoint_commits": len(tagged),
        "checkpoint_ids": len({i for c in tagged for i in c["checkpoints"]}),
        "checkpoint_refs": len(refs),
        "checkpoints": [{"sha": c["sha"][:7], "date": c["date"], "subject": c["subject"], "checkpoint": c["checkpoints"][0],
                         "url": ENTIRE + c["sha"], "commit_url": GH + c["sha"]} for c in tagged],
        "improvements": improvements(evidence, by_prefix),
    }


if __name__ == "__main__":
    ref = sys.argv[sys.argv.index("--ref") + 1] if "--ref" in sys.argv else "origin/main"
    out = ROOT / "frontend" / "public" / "built-with.json"
    data = build(ref)
    out.write_text(json.dumps(data, indent=1))
    print(f"built-with.json: {data['commits']} commits, {data['checkpoint_commits']} with Entire checkpoints, "
          f"{len(data['improvements'])} improvements")
