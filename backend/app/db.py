"""SQLite storage for audits. Small and synchronous; calls are cheap and serialised by a lock."""
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import config

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "prejudge.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS audits (
    id          TEXT PRIMARY KEY,
    repo_url    TEXT NOT NULL,
    repo_key    TEXT,              -- owner/name, lower-case
    head_sha    TEXT,              -- latest commit SHA when the audit was requested (cleared if not cacheable)
    commit_sha  TEXT,              -- same, never cleared: the per-repo cooldown compares it
    status      TEXT NOT NULL,     -- queued | quick_ready | complete | failed
    phase_quick TEXT DEFAULT 'queued',   -- queued | running | done | failed
    phase_deep  TEXT DEFAULT 'waiting',  -- waiting | available | queued | waiting_budget | running | done | failed | skipped
    is_example  INTEGER DEFAULT 0,
    run_kind    TEXT NOT NULL DEFAULT 'real',
    cached_from TEXT,              -- id of the audit whose result was reused
    steps       TEXT NOT NULL DEFAULT '[]',
    result      TEXT,
    error       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audits_cache ON audits (repo_key, head_sha, status);
CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id   TEXT NOT NULL,
    check_id   TEXT NOT NULL,       -- rubric check id or claim id
    is_wrong   INTEGER NOT NULL,
    note       TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS counters (   -- plain daily counts; no cookies, no per-user data
    day   TEXT NOT NULL,                  -- YYYY-MM-DD (UTC)
    name  TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, name)
);
CREATE TABLE IF NOT EXISTS projects (     -- one row per repo: history and the percentile cohort
    repo_key          TEXT PRIMARY KEY,
    repo_url          TEXT NOT NULL,
    first_seen        TEXT NOT NULL,
    last_audit_at     TEXT,
    last_audit_id     TEXT,
    audit_count       INTEGER NOT NULL DEFAULT 0,
    deep_count        INTEGER NOT NULL DEFAULT 0,
    latest_score      INTEGER,
    best_score        INTEGER,
    is_hackathon_repo INTEGER NOT NULL DEFAULT 0,  -- has commits inside the hackathon window
    last_deep_sha     TEXT,                        -- commit of the last finished deep check
    last_deep_id      TEXT,
    last_deep_version TEXT                         -- check logic version it ran with
);
CREATE TABLE IF NOT EXISTS roasts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_key   TEXT,
    style      TEXT,
    roast      TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

_lock = threading.RLock()  # re-entrant: _db() may connect() while the lock is held
_conn: sqlite3.Connection | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str | Path | None = None) -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = sqlite3.connect(str(path or config.env("PREJUDGE_DB") or DEFAULT_PATH),
                                check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
        _migrate(_conn)
        _conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after a db file was created (no data loss)."""
    have = {r[1] for r in conn.execute("PRAGMA table_info(audits)")}
    for col, ddl in (("phase_quick", "TEXT DEFAULT 'queued'"), ("phase_deep", "TEXT DEFAULT 'waiting'"),
                     ("is_example", "INTEGER DEFAULT 0"), ("hidden", "INTEGER DEFAULT 0"),
                     ("hidden_at", "TEXT"), ("hidden_reason", "TEXT"), ("commit_sha", "TEXT")):
        if col not in have:
            conn.execute(f"ALTER TABLE audits ADD COLUMN {col} {ddl}")
    conn.execute("UPDATE audits SET status = 'complete' WHERE status = 'done'")  # M2 naming


def _db() -> sqlite3.Connection:
    if _conn is None:
        connect()
    return _conn


def create(audit_id: str, repo_url: str, repo_key: str | None, head_sha: str | None,
           run_kind: str, status: str = "queued", **extra) -> None:
    now = _now()
    row = {"id": audit_id, "repo_url": repo_url, "repo_key": repo_key, "head_sha": head_sha, "commit_sha": head_sha,
           "status": status, "run_kind": run_kind, "created_at": now, "updated_at": now}
    row.update({k: json.dumps(v) if k in ("steps", "result") else v for k, v in extra.items()})
    cols = ", ".join(row)
    with _lock:
        _db().execute(f"INSERT INTO audits ({cols}) VALUES ({', '.join('?' * len(row))})",
                      list(row.values()))
        _db().commit()


def update(audit_id: str, **fields) -> None:
    fields = {k: json.dumps(v) if k in ("steps", "result") else v for k, v in fields.items()}
    fields["updated_at"] = _now()
    sets = ", ".join(f"{k} = ?" for k in fields)
    with _lock:
        _db().execute(f"UPDATE audits SET {sets} WHERE id = ?", [*fields.values(), audit_id])
        _db().commit()


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    d["steps"] = json.loads(d["steps"] or "[]")
    d["result"] = json.loads(d["result"]) if d["result"] else None
    return d


def get(audit_id: str) -> dict | None:
    with _lock:
        return _row(_db().execute("SELECT * FROM audits WHERE id = ?", (audit_id,)).fetchone())


def find_cached(repo_key: str, head_sha: str) -> dict | None:
    """Most recent reusable audit of this exact commit: complete first, else quick_ready.
    Only LLM-written results keep a head_sha (templates are retried), see jobs.cacheable."""
    with _lock:
        r = _db().execute(
            "SELECT * FROM audits WHERE repo_key = ? AND head_sha = ? AND status IN ('complete', 'quick_ready') "
            "AND cached_from IS NULL AND hidden = 0 ORDER BY status = 'complete' DESC, created_at DESC LIMIT 1",
            (repo_key, head_sha)).fetchone()
    return _row(r)


def _degraded(row: dict) -> bool:
    """A deep run that couldn't judge the claims (flagged, or older rows: seen in the steps)."""
    if (row["result"] or {}).get("deep_degraded"):
        return True
    return any(s.get("name") in ("claims.llm_failed", "verify.llm_failed") for s in row["steps"] or [])


def find_reusable(repo_key: str, commit_sha: str, checks_version: str) -> dict | None:
    """Most recent finished audit of this exact commit with the same check logic (complete first).
    Unlike find_cached, template verdicts count too: the caller decides whether to retry them."""
    with _lock:
        rows = _db().execute(
            "SELECT * FROM audits WHERE repo_key = ? AND commit_sha = ? AND status IN ('complete', 'quick_ready') "
            "AND cached_from IS NULL AND hidden = 0 AND is_example = 0 "
            "ORDER BY status = 'complete' DESC, created_at DESC LIMIT 10", (repo_key, commit_sha)).fetchall()
    for r in rows:
        row = _row(r)
        if (row["result"] or {}).get("checks_version") == checks_version \
                and not _degraded(row):
            return row
    return None


def find_deep_result(repo_key: str, commit_sha: str, checks_version: str) -> dict | None:
    """A finished deep check of this commit with the same check logic, for deep-check reuse."""
    with _lock:
        rows = _db().execute(
            "SELECT * FROM audits WHERE repo_key = ? AND commit_sha = ? AND status = 'complete' AND hidden = 0 "
            "AND is_example = 0 ORDER BY created_at DESC LIMIT 10", (repo_key, commit_sha)).fetchall()
    for r in rows:
        row = _row(r)
        if (row["result"] or {}).get("checks_version") == checks_version \
                and not _degraded(row):
            return row
    return None


def previous_audits(repo_key: str, before: str, exclude_id: str, run_kind: str) -> list[dict]:
    """Earlier audits of this repo, newest first (for "+22 since your last check")."""
    with _lock:
        rows = _db().execute(
            "SELECT * FROM audits WHERE repo_key = ? AND id != ? AND created_at <= ? AND run_kind = ? "
            "AND status IN ('complete', 'quick_ready') AND hidden = 0 AND is_example = 0 "
            "AND cached_from IS NULL AND rowid < (SELECT COALESCE(MAX(rowid), 1e18) FROM audits WHERE id = ?) "
            "ORDER BY created_at DESC, rowid DESC LIMIT 10", (repo_key, exclude_id, before, run_kind, exclude_id)).fetchall()
    return [_row(r) for r in rows]


def find_in_progress(repo_key: str, head_sha: str) -> dict | None:
    """An audit of this exact commit whose quick phase is still running: follow it instead."""
    with _lock:
        r = _db().execute(
            "SELECT * FROM audits WHERE repo_key = ? AND head_sha = ? AND status = 'queued' "
            "AND cached_from IS NULL ORDER BY created_at DESC LIMIT 1", (repo_key, head_sha)).fetchone()
    return _row(r)


def recent_for_repo(repo_key: str, within_s: int) -> dict | None:
    """Per-repo cooldown: the latest visible, not-failed audit of this repo from the last `within_s`
    (the caller only reuses it when the repo has no newer commit)."""
    since = (datetime.now(timezone.utc) - timedelta(seconds=within_s)).isoformat(timespec="seconds")
    with _lock:
        r = _db().execute(
            "SELECT * FROM audits WHERE repo_key = ? AND created_at >= ? AND status != 'failed' AND hidden = 0 "
            "AND is_example = 0 ORDER BY created_at DESC LIMIT 1", (repo_key, since)).fetchone()
    return _row(r)


def set_hidden(audit_id: str, hidden: bool, reason: str = "") -> None:
    """Removal request: hide from public view (the row is kept so an admin can restore it)."""
    with _lock:
        _db().execute("UPDATE audits SET hidden = ?, hidden_at = ?, hidden_reason = ? WHERE id = ?",
                      (int(hidden), _now() if hidden else None, reason[:300] if hidden else None, audit_id))
        _db().commit()


def hidden_audits(limit: int = 200) -> list[dict]:
    with _lock:
        rows = _db().execute("SELECT id, repo_url, hidden_at, hidden_reason FROM audits WHERE hidden = 1 "
                             "ORDER BY hidden_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def bump(name: str, n: int = 1) -> None:
    day = datetime.now(timezone.utc).date().isoformat()
    with _lock:
        _db().execute("INSERT INTO counters (day, name, count) VALUES (?, ?, ?) "
                      "ON CONFLICT (day, name) DO UPDATE SET count = count + excluded.count", (day, name, n))
        _db().commit()


def today_count(name: str) -> int:
    day = datetime.now(timezone.utc).date().isoformat()
    with _lock:
        r = _db().execute("SELECT count FROM counters WHERE day = ? AND name = ?", (day, name)).fetchone()
    return r[0] if r else 0


def today_counters(prefix: str) -> dict[str, int]:
    day = datetime.now(timezone.utc).date().isoformat()
    with _lock:
        rows = _db().execute("SELECT name, count FROM counters WHERE day = ? AND name LIKE ?",
                             (day, prefix.replace("%", "") + "%")).fetchall()
    return {r[0]: r[1] for r in rows}


# ---------------------------------------------------------------- projects

def upsert_project(repo_key: str, repo_url: str, audit_id: str, score: int | None, is_hackathon: bool,
                   deep: bool = False, deep_sha: str | None = None, checks_version: str | None = None,
                   new_audit: bool = True) -> None:
    """Called when a phase finishes. new_audit=False for the deep phase of an audit already counted."""
    now = _now()
    with _lock:
        _db().execute(
            "INSERT INTO projects (repo_key, repo_url, first_seen) VALUES (?, ?, ?) ON CONFLICT (repo_key) DO NOTHING",
            (repo_key, repo_url, now))
        _db().execute(
            "UPDATE projects SET repo_url = ?, last_audit_at = ?, last_audit_id = ?, "
            "audit_count = audit_count + ?, deep_count = deep_count + ?, "
            "latest_score = COALESCE(?, latest_score), "
            "best_score = MAX(COALESCE(best_score, -1), COALESCE(?, -1)), "
            "is_hackathon_repo = MAX(is_hackathon_repo, ?) WHERE repo_key = ?",
            (repo_url, now, audit_id, int(new_audit), int(deep), score, score, int(is_hackathon), repo_key))
        if deep and deep_sha:
            _db().execute("UPDATE projects SET last_deep_sha = ?, last_deep_id = ?, last_deep_version = ? "
                          "WHERE repo_key = ?", (deep_sha, audit_id, checks_version, repo_key))
        _db().execute("UPDATE projects SET best_score = NULL WHERE repo_key = ? AND best_score = -1", (repo_key,))
        _db().commit()


def get_project(repo_key: str) -> dict | None:
    with _lock:
        r = _db().execute("SELECT * FROM projects WHERE repo_key = ?", (repo_key,)).fetchone()
    return dict(r) if r else None


def all_projects(limit: int = 500) -> list[dict]:
    with _lock:
        rows = _db().execute("SELECT * FROM projects ORDER BY last_audit_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def cohort_rows(exclude_repo: str | None) -> list[dict]:
    """Latest visible real audit (scored) per hackathon repo: the anonymous percentile cohort."""
    with _lock:
        rows = _db().execute(
            "SELECT a.repo_key, a.result FROM audits a JOIN projects p ON p.repo_key = a.repo_key "
            "WHERE p.is_hackathon_repo = 1 AND a.run_kind = 'real' AND a.hidden = 0 AND a.is_example = 0 "
            "AND a.status IN ('complete', 'quick_ready') AND a.repo_key != ? "
            "AND a.created_at = (SELECT MAX(b.created_at) FROM audits b WHERE b.repo_key = a.repo_key "
            "  AND b.run_kind = 'real' AND b.hidden = 0 AND b.is_example = 0 AND b.status IN ('complete', 'quick_ready'))",
            (exclude_repo or "",)).fetchall()
    out, seen = [], set()
    for repo_key, result in rows:
        if repo_key in seen or not result:
            continue
        seen.add(repo_key)
        out.append({"repo_key": repo_key, "result": json.loads(result)})
    return out


def recent_audits(limit: int = 50) -> list[dict]:
    with _lock:
        rows = _db().execute(
            "SELECT id, repo_url, repo_key, status, phase_deep, run_kind, cached_from, hidden, created_at, "
            "json_extract(result, '$.score.score') AS score, "
            "json_extract(result, '$.usage.total_tokens') AS tokens FROM audits WHERE is_example = 0 "
            "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def all_feedback() -> list[dict]:
    with _lock:
        rows = _db().execute(
            "SELECT f.id, f.audit_id, a.repo_url, f.check_id, f.is_wrong, f.note, f.created_at "
            "FROM feedback f LEFT JOIN audits a ON a.id = f.audit_id ORDER BY f.id").fetchall()
    return [dict(r) for r in rows]


def metrics() -> dict:
    """Per-day counts (UTC). Audits come from the audits table (real runs only); everything
    else from counters. Cached copies are counted separately from audits that did work."""
    days: dict[str, dict] = {}
    with _lock:
        for day, new, cached, completed in _db().execute(
                "SELECT substr(created_at, 1, 10), SUM(cached_from IS NULL), SUM(cached_from IS NOT NULL), "
                "SUM(status = 'complete') FROM audits WHERE run_kind = 'real' AND is_example = 0 "
                "GROUP BY 1").fetchall():
            days.setdefault(day, {}).update(audits=new or 0, audits_cached=cached or 0, complete=completed or 0)
        for day, name, count in _db().execute("SELECT day, name, count FROM counters").fetchall():
            days.setdefault(day, {})[name] = count
        hidden = _db().execute("SELECT COUNT(*) FROM audits WHERE hidden = 1").fetchone()[0]
    rows = [{"day": d, **v} for d, v in sorted(days.items())]
    keys = sorted({k for r in rows for k in r if k != "day"})
    totals = {k: sum(r.get(k, 0) for r in rows) for k in keys}
    return {"days": rows, "totals": totals, "hidden_audits": hidden}


def mark_interrupted() -> int:
    """On startup: jobs that were in memory when the server stopped can't resume."""
    with _lock:
        c = _db().execute(
            "UPDATE audits SET status = 'failed', phase_quick = 'failed', error = 'server restarted' "
            "WHERE status = 'queued'")
        d = _db().execute(
            "UPDATE audits SET phase_deep = 'available', error = 'server restarted during deep check; ask again' "
            "WHERE status = 'quick_ready' AND phase_deep IN ('queued', 'running', 'waiting_budget')")
        _db().commit()
        return c.rowcount + d.rowcount


def add_feedback(audit_id: str, check_id: str, is_wrong: bool, note: str) -> None:
    with _lock:
        _db().execute("INSERT INTO feedback (audit_id, check_id, is_wrong, note, created_at) VALUES (?, ?, ?, ?, ?)",
                      (audit_id, check_id, int(is_wrong), note, _now()))
        _db().commit()


def feedback_for(audit_id: str) -> list[dict]:
    with _lock:
        rows = _db().execute("SELECT check_id, is_wrong, note FROM feedback WHERE audit_id = ?", (audit_id,)).fetchall()
    return [dict(r) for r in rows]


def seed_examples(folder: Path | None = None) -> int:
    """Load saved real audits (fixtures/audits) as example results, once."""
    folder = folder or Path(__file__).resolve().parent.parent / "fixtures" / "audits"
    added = 0
    for f in sorted(folder.glob("*.json")) if folder.exists() else []:
        report = json.loads(f.read_text())
        aid = report["audit_id"]
        if get(aid):
            continue
        create(aid, report["repo_url"], report["repo"]["full_name"].lower(), None, report.get("run_kind", "real"),
               status="complete", phase_quick="done", phase_deep="done", is_example=1,
               steps=report["steps"], result=report)
        added += 1
    return added


def examples(limit: int = 3) -> list[dict]:
    with _lock:
        rows = _db().execute("SELECT * FROM audits WHERE is_example = 1 AND hidden = 0 ORDER BY created_at, id LIMIT ?",
                             (limit,)).fetchall()
    return [_row(r) for r in rows]


def stats() -> dict:
    with _lock:
        total, real, done = _db().execute(
            "SELECT COUNT(*), SUM(run_kind = 'real'), SUM(status = 'complete' AND run_kind = 'real') "
            "FROM audits WHERE is_example = 0").fetchone()  # built-in examples aren't visitors' audits
    return {"total_audits": real or 0, "completed_audits": done or 0, "including_test_runs": total or 0}


def add_roast(repo_key: str | None, style: str, roast: str) -> None:
    with _lock:
        _db().execute("INSERT INTO roasts (repo_key, style, roast, created_at) VALUES (?, ?, ?, ?)",
                      (repo_key, style, roast, _now()))
        _db().commit()


def recent_roasts(limit: int = 20, exclude_repo: str | None = None) -> list[str]:
    """Other repos' recent roasts (a repo's own earlier roast may share its facts and phrasing)."""
    with _lock:
        rows = _db().execute("SELECT roast FROM roasts WHERE COALESCE(repo_key, '') != ? ORDER BY id DESC LIMIT ?",
                             ((exclude_repo or "").lower(), limit)).fetchall()
    return [r[0] for r in rows]
