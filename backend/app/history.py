"""Project history: score progress between checks and anonymous percentiles.

Progress compares an audit with the same repo's previous scored audit ("+22 since your last
check (46 → 68)") and names the checks that went to pass. Percentiles compare a score with the
cohort: the latest real audit of every repo with commits inside the hackathon window, excluding
removed audits, test runs and our own repo. Only aggregate numbers ever leave this module:
never another repo's name or score.
"""
import re
import threading
import time
from datetime import datetime, timezone

from app import config, db

MIN_COHORT = 15
COHORT_TTL_S = 600
OWN_REPO = "durgapritam/neathack-qbits-"

# key checks shown with a cohort percentage, and how a "pass" reads
KEY_CHECKS = {
    "demo_video": "a demo video under 3:00",
    "entire_checkpoints": "Entire checkpoints",
    "cfo_ai_plan": "a cfo.ai business plan",
    "before_after": "a before/after comparison with numbers",
    "failure_recovery": "a documented failure-and-recovery run",
}


def is_hackathon_repo(report: dict) -> bool:
    c = next((c for c in report.get("checks", []) if c["id"] == "commits_in_window"), None)
    m = re.match(r"(\d+) inside", (c or {}).get("detail", ""))
    return bool(m and int(m.group(1)) > 0)


def _score(result: dict | None) -> int | None:
    return ((result or {}).get("score") or {}).get("score")


def _statuses(result: dict | None) -> dict[str, tuple[str, str]]:
    return {c["id"]: (c["status"], c["title"]) for c in (result or {}).get("checks", [])}


def _comparable_score(previous: dict, deep: bool) -> int | None:
    """The previous audit's score from the same phase: deep scores run higher than quick ones.
    Older complete audits didn't keep their quick score, so they can't be compared to a quick one."""
    r = previous.get("result") or {}
    if deep:
        return _score(r) if previous.get("status") == "complete" else None
    if previous.get("status") == "complete":
        return r.get("quick_score")
    return _score(r)


def progress(previous: dict, result: dict) -> dict | None:
    """Score delta and fixed/regressed checks between two audits of the same repo (same phase)."""
    deep = result.get("phase") == "complete" or result.get("mode") == "full"
    old, new = _comparable_score(previous, deep), _score(result)
    if old is None or new is None:
        return None
    before, after = _statuses(previous.get("result")), _statuses(result)
    fixed = [after[k][1] for k in after if after[k][0] == "pass" and before.get(k, ("",))[0] in ("fail", "warn")]
    regressed = [after[k][1] for k in after if before.get(k, ("",))[0] == "pass" and after[k][0] in ("fail", "warn")]
    delta = new - old
    if delta > 0:
        text = f"+{delta} since your last check ({old} → {new})"
    elif delta == 0:
        text = f"Same score as your last check ({new})"
    else:
        text = f"{delta} since your last check ({old} → {new})"
    return {"previous_audit_id": previous["id"], "previous_at": previous["created_at"], "previous_score": old,
            "score": new, "delta": delta, "text": text, "fixed": fixed, "regressed": regressed}


def attach_progress(audit_id: str, repo_key: str | None, run_kind: str, created_at: str, result: dict) -> dict:
    """Add result["progress"] when this repo was checked before. Never fails the audit."""
    if not repo_key:
        return result
    try:
        # the most recent earlier audit with a score from the same phase
        prevs = [r for r in db.previous_audits(repo_key, created_at, audit_id, run_kind) if not db._degraded(r)]
        p = next((x for x in (progress(prev, result) for prev in prevs) if x), None)
    except Exception:
        p = None
    if p:
        result["progress"] = p
    else:
        result.pop("progress", None)
    return result


def record(audit_id: str, row: dict, result: dict, deep: bool) -> None:
    """Update the projects table when a phase finishes."""
    if not row.get("repo_key") or row.get("is_example"):
        return
    from app.tools.rubric import CHECKS_VERSION
    try:
        db.upsert_project(row["repo_key"], row["repo_url"], audit_id, _score(result), is_hackathon_repo(result),
                          deep=deep, deep_sha=row.get("commit_sha") if deep else None,
                          checks_version=CHECKS_VERSION, new_audit=not deep)
    except Exception:
        pass  # bookkeeping must never break an audit


# ---------------------------------------------------------------- percentiles

class Cohort:
    """Aggregate stats over the cohort, recomputed at most every COHORT_TTL_S seconds."""

    def __init__(self, ttl_s: float = COHORT_TTL_S, clock=time.monotonic):
        self.ttl_s, self.clock = ttl_s, clock
        self._at = -1e18
        self._stats: dict | None = None
        self._lock = threading.Lock()

    def invalidate(self) -> None:
        with self._lock:
            self._at = -1e18

    def stats(self) -> dict:
        with self._lock:
            if self._stats is None or self.clock() - self._at >= self.ttl_s:
                self._stats = self._compute()
                self._at = self.clock()
            return self._stats

    def _compute(self) -> dict:
        own = config.env("OWN_REPO", OWN_REPO).lower()
        rows = db.cohort_rows(own)
        scores = {r["repo_key"]: _score(r["result"]) for r in rows if _score(r["result"]) is not None}
        passes = {cid: {r["repo_key"] for r in rows if _statuses(r["result"]).get(cid, ("",))[0] == "pass"}
                  for cid in KEY_CHECKS}
        return {"size": len(scores), "scores": scores, "passes": passes,
                "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


COHORT = Cohort()


def percentiles(repo_key: str | None, result: dict | None, cohort: Cohort | None = None) -> dict | None:
    """Anonymous, positive comparisons for one audit, or None while the cohort is too small."""
    score = _score(result)
    if score is None:
        return None
    stats = (cohort or COHORT).stats()
    others = {k: v for k, v in stats["scores"].items() if k != (repo_key or "")}
    if len(others) < MIN_COHORT:
        return None
    beats = round(100 * sum(1 for v in others.values() if v < score) / len(others))
    mine = _statuses(result)
    checks = []
    for cid, what in KEY_CHECKS.items():
        have = stats["passes"][cid] - {repo_key}
        pct = round(100 * len(have) / len(others))
        passed = mine.get(cid, ("",))[0] == "pass"
        if passed:
            lead = "Only " if pct < 50 else ""
            text = f"{lead}{pct}% of teams have {what}. You're one of them ✅"
        else:
            text = f"{pct}% of teams already have {what}."
        checks.append({"check_id": cid, "pct": pct, "passed": passed, "text": text})
    return {"cohort_size": len(others), "beats_pct": beats,
            "text": f"Your score beats {beats}% of neatHack repos we've checked", "checks": checks}


def backfill() -> int:
    """Build projects rows from audits saved before the table existed (once: only while it's empty)."""
    if db.all_projects(limit=1):
        return 0
    with db._lock:
        rows = db._db().execute(
            "SELECT * FROM audits WHERE is_example = 0 AND cached_from IS NULL "
            "AND status IN ('complete', 'quick_ready') ORDER BY created_at, rowid").fetchall()
    n = 0
    for r in rows:
        row = db._row(r)
        result = row["result"] or {}
        record(row["id"], row, result, deep=False)
        if row["status"] == "complete":
            record(row["id"], row, result, deep=True)
        n += 1
    return n
