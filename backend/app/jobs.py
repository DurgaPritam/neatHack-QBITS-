"""Audit queues: quick by default, deep on request.

quick lane -> deterministic checks + short verdict, saved as "quick_ready"
deep lane  -> only when asked (POST /api/audits/{id}/deep): claim verification + rescore,
              saved as "complete"; one at a time, low LLM priority

The deep lane never degrades to a weaker model: if no JUDGE_MODELS have daily budget it
waits (phase_deep = "waiting_budget") and retries, keeping its place in the queue.
"""
import asyncio
import logging
import time
from collections import OrderedDict, deque

from app import db, history, replay
from app.llm import POOL, BudgetExhausted, judge_models
from app.steps import StepLog

log = logging.getLogger(__name__)
QUICK_TIMEOUT_S = 60
DEEP_TIMEOUT_S = 180
DEEP_EST_TOKENS = 16_000        # measured average deep phase (EVIDENCE.md)
BUDGET_RECHECK_S = 120          # how often a waiting deep audit re-checks the budget
CTX_CACHE_SIZE = 50             # quick-phase context kept for a later deep request


async def _run_quick(repo_url: str, audit_id: str, run_kind: str, steps: StepLog, ctx: dict,
                     use_reserve: bool = False) -> dict:
    from app.audit import run_quick_audit  # lazy, so tests can patch these

    return await run_quick_audit(repo_url, audit_id=audit_id, run_kind=run_kind, log=steps, ctx=ctx,
                                 use_reserve=use_reserve)


async def _run_deep(report: dict, ctx: dict, steps: StepLog, use_reserve: bool = False) -> dict:
    from app.audit import run_deep_audit

    return await run_deep_audit(report, ctx, log=steps, use_reserve=use_reserve)


async def _rebuild_ctx(report: dict) -> dict:
    from app.audit import rebuild_context

    return await rebuild_context(report)


def deep_budget_ok(use_reserve: bool) -> bool:
    if replay.mode() == "replay":
        return True  # replay spends no tokens
    from app.llm import configured_models
    return any(POOL.daily_ok(m, DEEP_EST_TOKENS, use_reserve) for m in judge_models() or configured_models())


DEGRADED_STEPS = {"claims.llm_failed", "verify.llm_failed"}


def degraded(result: dict) -> bool:
    """The deep phase finished but couldn't judge the claims (LLM errors or no quota)."""
    return any(s.get("name") in DEGRADED_STEPS for s in result.get("steps") or [])


def cacheable(result: dict) -> bool:
    """Reuse only results the LLM actually wrote; a template (cooling) verdict should be retried."""
    return (result.get("verdict") or {}).get("source") == "llm"


def _priority(payload) -> int:
    return payload[1] if isinstance(payload, tuple) and len(payload) == 2 else 0


class Lane:
    """A FIFO lane with one worker, visible positions and a moving-average duration."""

    def __init__(self, name: str, default_s: float):
        self.name = name
        self.pending: deque = deque()
        self.running: tuple[str, float] | None = None     # (audit_id, started_at)
        self.avg_s = default_s
        self.waiting_budget = False
        self._wake: asyncio.Event | None = None

    def start(self) -> None:
        self._wake = asyncio.Event()

    def put(self, audit_id: str, payload, front: bool = False, priority: int = 0) -> None:
        """front: back at the head (waiting for budget). Otherwise higher priority goes ahead of
        lower, FIFO within the same priority (hackathon repos are priority 1)."""
        if front:
            self.pending.appendleft((audit_id, payload))
        else:
            at = next((i for i, (_, p) in enumerate(self.pending) if _priority(p) < priority), len(self.pending))
            self.pending.insert(at, (audit_id, payload))
        self._wake.set()

    def __contains__(self, audit_id: str) -> bool:
        return (self.running and self.running[0] == audit_id) or any(a == audit_id for a, _ in self.pending)

    async def get(self):
        while not self.pending:
            self._wake.clear()
            await self._wake.wait()
        return self.pending.popleft()

    def observe(self, seconds: float) -> None:
        self.avg_s = 0.7 * self.avg_s + 0.3 * seconds

    def length(self) -> int:
        return len(self.pending) + (1 if self.running else 0)

    def position(self, audit_id: str) -> dict | None:
        """1 = running now; n = n-1 audits ahead of it. None if not in this lane."""
        now = time.monotonic()
        current_left = max(0.0, self.avg_s - (now - self.running[1])) if self.running else 0.0
        base = {"lane": self.name, "waiting_for_budget": self.waiting_budget}
        if self.running and self.running[0] == audit_id:
            return {**base, "position": 1, "estimated_wait_s": round(current_left)}
        for i, (aid, _) in enumerate(self.pending):
            if aid == audit_id:
                ahead = i + (1 if self.running else 0)
                return {**base, "position": ahead + 1,
                        "estimated_wait_s": round(current_left + i * self.avg_s + self.avg_s)}
        return None


class AuditQueues:
    def __init__(self) -> None:
        self.quick = Lane("quick", default_s=10)
        self.deep = Lane("deep", default_s=45)
        self.ctx_cache: OrderedDict[str, dict] = OrderedDict()
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

    async def submit(self, audit_id: str, repo_url: str, run_kind: str, use_reserve: bool = False) -> dict:
        self.quick.put(audit_id, (repo_url, run_kind, use_reserve))
        return self.position(audit_id)

    def request_deep(self, audit_id: str, use_reserve: bool = False, priority: int = 0) -> dict:
        if audit_id not in self.deep:
            db.update(audit_id, phase_deep="queued")
            self.deep.put(audit_id, (use_reserve, priority), priority=priority)
        return self.position(audit_id)

    def position(self, audit_id: str) -> dict | None:
        return self.quick.position(audit_id) or self.deep.position(audit_id)

    def _remember_ctx(self, audit_id: str, ctx: dict) -> None:
        self.ctx_cache[audit_id] = ctx
        self.ctx_cache.move_to_end(audit_id)
        while len(self.ctx_cache) > CTX_CACHE_SIZE:
            self.ctx_cache.popitem(last=False)

    # ---------------------------------------------------------------- workers

    async def _quick_worker(self) -> None:
        while True:
            audit_id, (repo_url, run_kind, use_reserve) = await self.quick.get()
            self.quick.running = (audit_id, time.monotonic())
            try:
                await self._quick(audit_id, repo_url, run_kind, use_reserve)
            except Exception:
                log.exception("quick phase crashed for %s", audit_id)
            finally:
                self.quick.observe(time.monotonic() - self.quick.running[1])
                self.quick.running = None

    async def _quick(self, audit_id: str, repo_url: str, run_kind: str, use_reserve: bool) -> None:
        db.update(audit_id, phase_quick="running")
        steps = StepLog(on_change=lambda s: db.update(audit_id, steps=s.to_list()))
        ctx: dict = {}
        try:
            report = await asyncio.wait_for(_run_quick(repo_url, audit_id, run_kind, steps, ctx, use_reserve),
                                            QUICK_TIMEOUT_S)
        except Exception as exc:  # timeout or bug: keep the steps so far as a partial record
            steps.note("quick.crashed", f"{type(exc).__name__}: {str(exc)[:200]}", status="failed")
            db.update(audit_id, status="failed", phase_quick="failed", phase_deep="skipped",
                      error=type(exc).__name__, steps=steps.to_list())
            return
        deep_state = "available" if ctx.get("repo_available") else "skipped"
        row = db.get(audit_id) or {}
        report = history.attach_progress(audit_id, row.get("repo_key"), run_kind, row.get("created_at", ""), report)
        history.record(audit_id, row, report, deep=False)
        db.update(audit_id, status="quick_ready", phase_quick="done", phase_deep=deep_state,
                  steps=report.get("steps", steps.to_list()), result=report,
                  **({} if cacheable(report) else {"head_sha": None}))
        if ctx.get("repo_available"):
            self._remember_ctx(audit_id, ctx)

    async def _deep_worker(self) -> None:
        while True:
            audit_id, payload = await self.deep.get()
            use_reserve, priority = payload if isinstance(payload, tuple) else (payload, 0)
            if not deep_budget_ok(use_reserve):
                await self._wait_for_budget(audit_id, use_reserve, priority=priority)
                continue
            self.deep.running = (audit_id, time.monotonic())
            try:
                await self._deep(audit_id, use_reserve, priority)
            except Exception:
                log.exception("deep phase crashed for %s", audit_id)
            finally:
                self.deep.observe(time.monotonic() - self.deep.running[1])
                self.deep.running = None

    async def _wait_for_budget(self, audit_id: str, use_reserve: bool, retry_in: float | None = None,
                               priority: int = 0) -> None:
        """Keep the audit at the head of the deep queue until a judge model has budget."""
        self.deep.waiting_budget = True
        db.update(audit_id, phase_deep="waiting_budget")
        self.deep.put(audit_id, (use_reserve, priority), front=True)
        await asyncio.sleep(min(retry_in or BUDGET_RECHECK_S, BUDGET_RECHECK_S))
        self.deep.waiting_budget = not deep_budget_ok(use_reserve)

    async def _deep(self, audit_id: str, use_reserve: bool, priority: int = 0) -> None:
        row = db.get(audit_id)
        if row is None or not row["result"]:
            return
        report = row["result"]
        db.update(audit_id, phase_deep="running")
        steps = StepLog.from_list(row["steps"], on_change=lambda s: db.update(audit_id, steps=s.to_list()))
        try:
            ctx = self.ctx_cache.get(audit_id)
            if ctx is None:
                steps.note("deep.rebuild_context", "quick-phase context expired; re-reading the repo (no LLM)")
                ctx = await _rebuild_ctx(report)
            result = await asyncio.wait_for(_run_deep(report, ctx, steps, use_reserve), DEEP_TIMEOUT_S)
        except BudgetExhausted as exc:
            steps.note("deep.waiting_budget", f"{exc}; waiting instead of using a weaker model")
            db.update(audit_id, steps=steps.to_list())
            await self._wait_for_budget(audit_id, use_reserve, exc.retry_in_s, priority)
            return
        except Exception as exc:
            # The quick result stays available; the audit is just not deepened.
            steps.note("deep.crashed", f"{type(exc).__name__}: {str(exc)[:200]}", status="failed")
            db.update(audit_id, phase_deep="failed", error=f"deep: {type(exc).__name__}", steps=steps.to_list())
            return
        self.ctx_cache.pop(audit_id, None)
        db.bump("deep_completed")
        if degraded(result):
            result["deep_degraded"] = True  # claim judging failed: never hand this out as "the" deep result
        result = history.attach_progress(audit_id, row.get("repo_key"), row.get("run_kind", "real"),
                                         row.get("created_at", ""), result)
        history.record(audit_id, row, result, deep=True)
        db.update(audit_id, status="complete", phase_deep="done", steps=result.get("steps", steps.to_list()),
                  result=result, **({} if cacheable(result) else {"head_sha": None}))

    # ---------------------------------------------------------------- health

    def busy(self) -> bool:
        return self.deep.length() >= 4 or self.deep.avg_s * self.deep.length() > 300
