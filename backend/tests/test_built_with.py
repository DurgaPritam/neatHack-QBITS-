"""scripts/built_with.py: the /built-with story comes from git, Entire trailers and EVIDENCE.md."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "built_with.py"
spec = importlib.util.spec_from_file_location("built_with", SCRIPT)
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)

EVIDENCE = """# x
## 4. Before/after improvements

| Improvement | Before | After | Source |
|---|---|---|---|
| Deep tokens, `openai/swarm` | 40,086 | **10,145** | [`abc1234`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/abc1234) |
| Total time | 106 s | 36.7 s | same |
| No commit | 1 | 2 | `/api/admin/metrics` |

### Next section
| Improvement | ignored | x | y |
"""
COMMITS = {"abc1234" + "0" * 33: {"sha": "abc1234" + "0" * 33, "subject": "Faster deep phase", "checkpoints": ["01ABC"]}}


def by_prefix(p):
    return next((c for s, c in COMMITS.items() if s.startswith(p)), None)


def test_improvements_link_commit_and_checkpoint():
    rows = B.improvements(EVIDENCE, by_prefix)
    assert [r["improvement"] for r in rows] == ["Deep tokens, openai/swarm", "Total time", "No commit"]
    first = rows[0]
    assert first["after"] == "10,145" and first["commits"][0]["checkpoint"] == "01ABC"
    assert first["commits"][0]["checkpoint_url"] == "https://entire.io/gh/DurgaPritam/neatHack-QBITS-/commit/" + "abc1234" + "0" * 33
    assert rows[1]["commits"] == first["commits"]                 # "same" reuses the row above
    assert rows[2]["commits"] == []                               # nothing to link: no guess


def test_build_on_this_repo_uses_pushed_commits_only():
    d = B.build("origin/main")
    assert d["commits"] > 0 and d["checkpoint_commits"] <= d["commits"]
    assert all(c["url"].startswith("https://entire.io/gh/DurgaPritam/neatHack-QBITS-/commit/") for c in d["checkpoints"])
    assert d["improvements"]
