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
    status      TEXT NOT NULL,     -- queued | running | done | failed
    run_kind    TEXT NOT NULL DEFAULT 'real',
    cached_from TEXT,              -- id of the audit whose result was reused
    steps       TEXT NOT NULL DEFAULT '[]',
    result      TEXT,
    error       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audits_cache ON audits (repo_key, head_sha, status);
"""

_lock = threading.Lock()
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
        _conn.commit()


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
    """Most recent finished, non-reused audit of this exact commit."""
    with _lock:
        r = _db().execute(
            "SELECT * FROM audits WHERE repo_key = ? AND head_sha = ? AND status = 'done' "
            "AND cached_from IS NULL ORDER BY created_at DESC LIMIT 1", (repo_key, head_sha)).fetchone()
    return _row(r)


def stats() -> dict:
    with _lock:
        total, real, done = _db().execute(
            "SELECT COUNT(*), SUM(run_kind = 'real'), SUM(status = 'done' AND run_kind = 'real') "
            "FROM audits").fetchone()
    return {"total_audits": real or 0, "completed_audits": done or 0, "including_test_runs": total or 0}
