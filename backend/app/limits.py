"""Abuse protection: in-memory sliding-window limits per client IP.

One process, no Redis: counts reset on restart, which is fine for a hackathon-sized service.
Limits come from .env so they can be loosened for a demo without a deploy.
"""
import threading
import time
from collections import defaultdict, deque

from app import config


def _int(name: str, default: int) -> int:
    try:
        return int(config.env(name, str(default)))
    except ValueError:
        return default


class SlidingWindow:
    def __init__(self, limit: int, window_s: float):
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, now: float | None = None) -> float:
        """Record a hit. Returns 0 if allowed, else seconds until the next hit is allowed
        (a refused hit is not recorded)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] >= self.window_s:
                q.popleft()
            if len(q) >= self.limit:
                return max(1.0, self.window_s - (now - q[0]))
            q.append(now)
            if len(self._hits) > 10_000:  # drop idle keys so memory stays flat
                for k in [k for k, v in self._hits.items() if not v][:5_000]:
                    del self._hits[k]
            return 0.0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


AUDITS = SlidingWindow(_int("RATE_AUDITS_PER_10MIN", 5), 600)
DEEP = SlidingWindow(_int("RATE_DEEP_PER_HOUR", 3), 3600)
EVENTS = SlidingWindow(30, 60)          # card download / share click counters
REMOVALS = SlidingWindow(10, 3600)
DEEP_QUEUE_MAX = _int("DEEP_QUEUE_MAX", 10)
REPO_COOLDOWN_S = _int("REPO_COOLDOWN_S", 600)
# Daily budget protection (UTC days). The admin reserve in app.llm stays separate from these.
DEEP_DAILY_CAP = _int("DEEP_DAILY_CAP", 40)              # deep checks per day, all repos
DEEP_PER_REPO_DAILY = _int("DEEP_PER_REPO_DAILY", 3)     # deep checks per repo per day
PUBLIC_DAILY_TOKENS = _int("PUBLIC_DAILY_TOKENS", 350_000)  # LLM tokens per day for public traffic

MESSAGES = {
    "deep_daily": "Today's deep checks are used up. Your quick result is ready; try the deep check tomorrow.",
    "deep_repo": "This repo has had {n} deep checks today, the daily maximum. Your quick result is ready; "
                 "push your fixes and try the deep check tomorrow.",
    "public_tokens": "Today's AI budget for deep checks is used up. Your quick result is ready; "
                     "try the deep check tomorrow.",
    "deep_queue": "The deep-check queue is full ({n} waiting). Your quick result is saved; "
                  "try the deep check again in a few minutes.",
    "deep_ip": "You've used your {n} deep checks for this hour. Your quick result is saved.",
    "audits_ip": "Easy there: {n} new audits per 10 minutes per person.",
}


class LimitLog:
    """Recent limit hits for the admin page. In memory only: IPs are never written to disk."""

    def __init__(self, size: int = 300):
        self._hits: deque = deque(maxlen=size)
        self._lock = threading.Lock()

    def add(self, kind: str, ip: str | None = None, repo: str | None = None) -> None:
        with self._lock:
            self._hits.append({"at": time.time(), "kind": kind, "ip": ip, "repo": repo})

    def summary(self) -> dict:
        with self._lock:
            hits = list(self._hits)
        by_ip: dict[str, int] = defaultdict(int)
        by_repo: dict[str, int] = defaultdict(int)
        for h in hits:
            if h["ip"]:
                by_ip[h["ip"]] += 1
            if h["repo"]:
                by_repo[h["repo"]] += 1
        top = lambda d: sorted(({"key": k, "hits": v} for k, v in d.items()), key=lambda r: -r["hits"])[:20]
        return {"recent": hits[-50:][::-1], "by_ip": top(by_ip), "by_repo": top(by_repo)}

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


HITS = LimitLog()


def wait_text(seconds: float) -> str:
    return f"{round(seconds)}s" if seconds < 90 else f"{round(seconds / 60)} min"


def reset_all() -> None:
    for w in (AUDITS, DEEP, EVENTS, REMOVALS):
        w.reset()
    HITS.reset()
