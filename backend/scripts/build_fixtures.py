"""Build LLM replay fixtures (and example audits) from saved real audit reports.

    python -m scripts.build_fixtures report1.json report2.json ...

Groq's raw HTTP responses were not recorded before LLM_MODE=record existed, so each fixture is
rebuilt from what the real models returned in that audit, after parsing:
- claims, claim verdicts + evidence, estimates  <- report["agent"]
- quick and deep roasts                          <- real LLM roasts from the roast memory table
                                                   (template roasts are never stored there)
- fix wording and "best thing"                   <- report["verdict"]
The org id in Groq error messages is redacted. Writes fixtures/llm/*.json and fixtures/audits/*.json.
"""
import json
import re
import sys
from pathlib import Path

from app import db
from app.agent import roast as R
from app.replay import FIXTURE_DIR, fixture_path

AUDITS_DIR = FIXTURE_DIR.parent / "audits"


def redact(text: str) -> str:
    return re.sub(r"org_[a-z0-9]{10,}", "org_[redacted]", text)


def real_roasts(repo: str) -> list[str]:
    rows = db._db().execute("SELECT roast FROM roasts WHERE repo_key = ? ORDER BY id DESC", (repo,)).fetchall()
    return [r[0] for r in rows]


def build(path: str) -> str:
    report = json.loads(redact(Path(path).read_text()))
    repo = report["repo"]["full_name"].lower()
    agent = report["agent"]
    quick_facts = R.build_facts(report)
    deep_facts = R.build_facts(report, agent["claims"])
    ok_quick = [r for r in real_roasts(repo) if not R.roast_problems(r, quick_facts, [], report)]
    ok_deep = [r for r in real_roasts(repo) if not R.roast_problems(r, deep_facts, [], report)]
    if not ok_quick or not ok_deep:
        raise SystemExit(f"{repo}: no stored LLM roast passes the current roast rules")
    deep_roast = report["verdict"]["roast"] if report["verdict"]["roast"] in ok_deep else ok_deep[0]
    quick_roast = next((r for r in ok_quick if r != deep_roast), ok_quick[0])
    fixes = [{"check_id": f["check_id"], "fix": f["fix"]} for f in report["verdict"]["fixes"]]
    claims = [{"id": c["claim_id"], "text": c["claim"], "quote": c.get("quote", ""), "category": c.get("category", "agent")}
              for c in agent["claims"]]
    cited = []
    for c in agent["claims"]:
        for e in c["evidence"]:
            p = re.sub(r":\d+(-\d+)?$", "", e["ref"])
            if p and not p.lower().startswith("readme") and not p.startswith("http") and "." in p and p not in cited:
                cited.append(p)
    q_usage, d_usage = report["phases"]["quick"]["usage"], report["phases"]["deep"]["usage"]
    fixture = {
        "repo": repo,
        "source": f"rebuilt from real audit {report['audit_id']} ({report['audited_at']}); see scripts/build_fixtures.py",
        "responses": {
            "quick_verdict": {"roast": quick_roast, "fixes": fixes, "best_thing": report["verdict"]["best_thing"]},
            "claims": {"claims": claims, "injection_attempts": []},
            "verify": {"results": [{"claim_id": c["claim_id"], "status": c["status"], "evidence": c["evidence"],
                                    "reason": c["reason"]} for c in agent["claims"]],
                       "estimates": agent["estimates"], "injection_attempts": []},
            "verdict": {"roast": deep_roast, "fixes": fixes, "best_thing": report["verdict"]["best_thing"]},
        },
        # the replayed verify turn reads every cited file, so grounding re-checks the evidence
        "verify_tool_calls": [{"name": "read_file", "arguments": {"path": p}} for p in cited[:10]],
        "usage": {"quick_verdict": round(q_usage["total_tokens"] / max(q_usage["calls"], 1)),
                  "claims": round(d_usage["total_tokens"] / max(d_usage["calls"], 1)),
                  "verify": round(d_usage["total_tokens"] / max(d_usage["calls"], 1)),
                  "verdict": round(d_usage["total_tokens"] / max(d_usage["calls"], 1))},
    }
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    AUDITS_DIR.mkdir(parents=True, exist_ok=True)
    fixture_path(repo).write_text(json.dumps(fixture, indent=2, ensure_ascii=False))
    (AUDITS_DIR / fixture_path(repo).name).write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return f"{repo}: quick roast + deep roast + {len(claims)} claims, {len(cited)} evidence files"


if __name__ == "__main__":
    db.connect()
    for f in sys.argv[1:]:
        print(build(f))
