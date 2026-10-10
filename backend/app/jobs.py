"""Two-speed audit queues.

quick queue -> deterministic checks + short verdict, saved as "quick_ready" immediately
deep queue  -> claim verification + rescore, saved as "complete"; one at a time

The quick worker never waits on the deep worker: they are separate tasks, and deep-phase
LLM calls run at low priority (they leave quota headroom while a quick audit is in flight).
"""
import asyncio
import logging
import time
from collections import deque

from app import db
from app.steps import StepLog

log = logging.getLogger(__name__)
QUICK_TIMEOUT_S = 60
DEEP_TIMEOUT_S = 180


async def _run_quick(repo_url: str, audit_id: str, run_kind: str, steps: StepLog, ctx: dict) -> dict:
    from app.audit import run_quick_audit  # lazy, so tests can patch these

    return await run_quick_audit(repo_url, audit_id=audit_id, run_kind=run_kind, log=steps, ctx=ctx)


async def _run_deep(report: dict, ctx: dict, steps: StepLog) -> dict:
    from app.audit import run_deep_audit

    return await run_deep_audit(report, ctx, log=steps)


def cacheable(result: dict) -> bool:
    """Only reuse complete results; a rate-limited, template-only run should be retried."""
    return result.get("phase") == "complete" and (result.get("verdict") or {}).get("source") == "llm"


class Lane:
    """A FIFO lane with one worker, visible positions and a moving-average duration."""

    def __init__(self, name: str, default_s: float):
        self.name = name
        self.pending: deque = deque()
        self.running: tuple[str, float] | None = None     # (audit_id, started_at)
        self.avg_s = default_s
        self._wake: asyncio.Event | None = None

    def start(self) -> None:
        self._wake = asyncio.Event()

    def put(self, audit_id: str, payload) -> None:
        self.pending.append((audit_id, payload))
        self._wake.set()

    async def get(self):
        while not self.pending:
            self._wake.clear()
            await self._wake.wait()
        return self.pending.popleft()

    def observe(self, seconds: float) -> None:
        self.avg_s = 0.7 * self.avg_s + 0.3 * seconds

    def position(self, audit_id: str) -> dict | None:
        """1 = running now; n = n-1 audits ahead of it. None if not in this lane."""
        now = time.monotonic()
        current_left = max(0.0, self.avg_s - (now - self.running[1])) if self.running else 0.0
        if self.running and self.running[0] == audit_id:
            return {"lane": self.name, "position": 1, "estimated_wait_s": round(current_left)}
        for i, (aid, _) in enumerate(self.pending):
            if aid == audit_id:
                ahead = i + (1 if self.running else 0)
                return {"lane": self.name, "position": ahead + 1,
                        "estimated_wait_s": round(current_left + i * self.avg_s + self.avg_s)}
        return None


class AuditQueues:
    def __init__(self) -> None:
        self.quick = Lane("quick", default_s=15)
        self.deep = Lane("deep", default_s=60)
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        self.quick.start()
        self.deep.start()
        self._tasks = [asyncio.create_task(self._quick_worker()),
                       asyncio.create_task(self._deep_worker())]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass

    async def submit(self, audit_id: str, repo_url: str, run_kind: str) -> dict:
        self.quick.put(audit_id, (repo_url, run_kind))
        return self.position(audit_id)

    def position(self, audit_id: str) -> dict | None:
        q = self.quick.position(audit_id)
        if q:  # deep comes after quick: add a deep estimate on top
            return {**q, "estimated_complete_s": q["estimated_wait_s"] + round(self.deep.avg_s * (len(self.deep.pending) + 1))}
        return self.deep.position(audit_id)

    # ---------------------------------------------------------------- workers

    async def _quick_worker(self) -> None:
        while True:
            audit_id, (repo_url, run_kind) = await self.quick.get()
            self.quick.running = (audit_id, time.monotonic())
            try:
                await self._quick(audit_id, repo_url, run_kind)
            except Exception:
                log.exception("quick phase crashed for %s", audit_id)
            finally:
                self.quick.observe(time.monotonic() - self.quick.running[1])
                self.quick.running = None

    async def _quick(self, audit_id: str, repo_url: str, run_kind: str) -> None:
        db.update(audit_id, phase_quick="running")
        steps = StepLog(on_change=lambda s: db.update(audit_id, steps=s.to_list()))
        ctx: dict = {}
        try:
            report = await asyncio.wait_for(_run_quick(repo_url, audit_id, run_kind, steps, ctx), QUICK_TIMEOUT_S)
        except Exception as exc:  # timeout or bug: keep the steps so far as a partial record
            steps.note("quick.crashed", f"{type(exc).__name__}: {str(exc)[:200]}", status="failed")
            db.update(audit_id, status="failed", phase_quick="failed", phase_deep="skipped",
                      error=type(exc).__name__, steps=steps.to_list())
            return
        db.update(audit_id, status="quick_ready", phase_quick="done", phase_deep="queued",
                  steps=report.get("steps", steps.to_list()), result=report)
        self.deep.put(audit_id, (report, ctx, steps))   # the quick result is already saved

    async def _deep_worker(self) -> None:
        while True:
            audit_id, (report, ctx, steps) = await self.deep.get()
            self.deep.running = (audit_id, time.monotonic())
            try:
                await self._deep(audit_id, report, ctx, steps)
            except Exception:
                log.exception("deep phase crashed for %s", audit_id)
            finally:
                self.deep.observe(time.monotonic() - self.deep.running[1])
                self.deep.running = None

    async def _deep(self, audit_id: str, report: dict, ctx: dict, steps: StepLog) -> None:
        db.update(audit_id, phase_deep="running")
        steps.on_change = lambda s: db.update(audit_id, steps=s.to_list())
        try:
            result = await asyncio.wait_for(_run_deep(report, ctx, steps), DEEP_TIMEOUT_S)
        except Exception as exc:
            # The quick result stays available; the audit is just not deepened.
            steps.note("deep.crashed", f"{type(exc).__name__}: {str(exc)[:200]}", status="failed")
            db.update(audit_id, phase_deep="failed", error=f"deep: {type(exc).__name__}",
                      steps=steps.to_list(), head_sha=None)
            return
        db.update(audit_id, status="complete", phase_deep="done", steps=result.get("steps", steps.to_list()),
                  result=result,
                  # a degraded result keeps no SHA, so the next request re-runs it
                  **({} if cacheable(result) else {"head_sha": None}))
