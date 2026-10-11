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


def wait_text(seconds: float) -> str:
    return f"{round(seconds)}s" if seconds < 90 else f"{round(seconds / 60)} min"


def reset_all() -> None:
    for w in (AUDITS, DEEP, EVENTS, REMOVALS):
        w.reset()
