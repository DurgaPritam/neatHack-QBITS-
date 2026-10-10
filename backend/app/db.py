"""SQLite storage for audits. Small and synchronous; calls are cheap and serialised by a lock."""
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from app import config

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "prejudge.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS audits (
    id          TEXT PRIMARY KEY,
    repo_url    TEXT NOT NULL,
    repo_key    TEXT,              -- owner/name, lower-case
    head_sha    TEXT,              -- latest commit SHA when the audit was requested
    status      TEXT NOT NULL,     -- queued | quick_ready | complete | failed
    phase_quick TEXT DEFAULT 'queued',   -- queued | running | done | failed
    phase_deep  TEXT DEFAULT 'waiting',  -- waiting | queued | running | done | failed | skipped
    run_kind    TEXT NOT NULL DEFAULT 'real',
    cached_from TEXT,              -- id of the audit whose result was reused
    steps       TEXT NOT NULL DEFAULT '[]',
    result      TEXT,
    error       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audits_cache ON audits (repo_key, head_sha, status);
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
    for col, ddl in (("phase_quick", "TEXT DEFAULT 'queued'"), ("phase_deep", "TEXT DEFAULT 'waiting'")):
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
    row = {"id": audit_id, "repo_url": repo_url, "repo_key": repo_key, "head_sha": head_sha,
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
    """Most recent complete, non-reused audit of this exact commit."""
    with _lock:
        r = _db().execute(
            "SELECT * FROM audits WHERE repo_key = ? AND head_sha = ? AND status = 'complete' "
            "AND cached_from IS NULL ORDER BY created_at DESC LIMIT 1", (repo_key, head_sha)).fetchone()
    return _row(r)


def find_in_progress(repo_key: str, head_sha: str) -> dict | None:
    """An audit of this exact commit that is still running: reuse it instead of starting another."""
    with _lock:
        r = _db().execute(
            "SELECT * FROM audits WHERE repo_key = ? AND head_sha = ? AND status IN ('queued', 'quick_ready') "
            "AND cached_from IS NULL ORDER BY created_at DESC LIMIT 1", (repo_key, head_sha)).fetchone()
    return _row(r)


def mark_interrupted() -> int:
    """On startup: jobs that were in memory when the server stopped can't resume."""
    with _lock:
        c = _db().execute(
            "UPDATE audits SET status = 'failed', phase_quick = 'failed', error = 'server restarted' "
            "WHERE status = 'queued'")
        d = _db().execute(
            "UPDATE audits SET phase_deep = 'failed', error = 'server restarted before deep phase' "
            "WHERE status = 'quick_ready' AND phase_deep IN ('queued', 'running')")
        _db().commit()
        return c.rowcount + d.rowcount


def stats() -> dict:
    with _lock:
        total, real, done = _db().execute(
            "SELECT COUNT(*), SUM(run_kind = 'real'), SUM(status = 'complete' AND run_kind = 'real') "
            "FROM audits").fetchone()
    return {"total_audits": real or 0, "completed_audits": done or 0, "including_test_runs": total or 0}


def add_roast(repo_key: str | None, style: str, roast: str) -> None:
    with _lock:
        _db().execute("INSERT INTO roasts (repo_key, style, roast, created_at) VALUES (?, ?, ?, ?)",
                      (repo_key, style, roast, _now()))
        _db().commit()


def recent_roasts(limit: int = 20) -> list[str]:
    with _lock:
        rows = _db().execute("SELECT roast FROM roasts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [r[0] for r in rows]
