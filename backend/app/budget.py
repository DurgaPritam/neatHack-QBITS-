"""Daily LLM token budget, persisted per model per UTC day so restarts don't forget usage.

The QuotaPool counts tokens from responses and learns Groq's own numbers from TPD 429s;
this module stores that in SQLite and loads it back at startup.
"""
import time
from datetime import datetime, timezone

from app import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_budget (
    day           TEXT NOT NULL,
    model         TEXT NOT NULL,
    tokens_used   INTEGER NOT NULL DEFAULT 0,
    tpd_limit     INTEGER,
    blocked_until REAL,            -- unix time; Groq said "try again in ..."
    PRIMARY KEY (day, model)
);
"""


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def attach(pool) -> None:
    """Load today's usage into the pool and persist every change from now on."""
    with db._lock:
        db._db().executescript(SCHEMA)
        rows = db._db().execute("SELECT model, tokens_used, tpd_limit, blocked_until FROM llm_budget "
                                "WHERE day = ?", (_today(),)).fetchall()
    now_wall, now_mono = time.time(), pool.clock()
    for model, used, limit, blocked in rows:
        q = pool._q(model)
        pool._roll_day(q)
        q.tpd_used = max(q.tpd_used, used or 0)
        if limit:
            q.tpd_limit = limit
        if blocked and blocked > now_wall:
            q.daily_blocked_until = now_mono + (blocked - now_wall)

    def persist(model, q):
        blocked = time.time() + (q.daily_blocked_until - pool.clock()) if q.daily_blocked_until else None
        with db._lock:
            db._db().execute(
                "INSERT INTO llm_budget (day, model, tokens_used, tpd_limit, blocked_until) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(day, model) DO UPDATE SET tokens_used = excluded.tokens_used, "
                "tpd_limit = excluded.tpd_limit, blocked_until = excluded.blocked_until",
                (q.tpd_day or _today(), model, q.tpd_used, q.tpd_limit, blocked))
            db._db().commit()

    pool.persist = persist
