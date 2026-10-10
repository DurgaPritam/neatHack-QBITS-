"""Asyncio job queue: audits run one at a time (Groq free-tier rate limits)."""
import asyncio
import logging

from app import db
from app.steps import StepLog

log = logging.getLogger(__name__)
HARD_TIMEOUT_S = 180  # the agent has its own 120s budget; this is the last-resort guard


async def _run(repo_url: str, audit_id: str, run_kind: str, steps: StepLog) -> dict:
    from app.audit import run_full_audit  # imported lazily so tests can patch it

    return await run_full_audit(repo_url, audit_id=audit_id, run_kind=run_kind, log=steps)


def cacheable(result: dict) -> bool:
    """Only reuse complete results; a rate-limited, template-only run should be retried."""
    return (result.get("verdict") or {}).get("source") == "llm"


class AuditQueue:
    def __init__(self) -> None:
        self.queue: asyncio.Queue | None = None
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self.queue = asyncio.Queue()  # bound to the running loop, so created here
        self._task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def submit(self, audit_id: str, repo_url: str, run_kind: str) -> int:
        await self.queue.put((audit_id, repo_url, run_kind))
        return self.queue.qsize()

    async def _worker(self) -> None:
        while True:
            audit_id, repo_url, run_kind = await self.queue.get()
            try:
                await self._process(audit_id, repo_url, run_kind)
            except Exception:
                log.exception("audit %s crashed", audit_id)
            finally:
                self.queue.task_done()

    async def _process(self, audit_id: str, repo_url: str, run_kind: str) -> None:
        db.update(audit_id, status="running")
        steps = StepLog(on_change=lambda s: db.update(audit_id, steps=s.to_list()))
        try:
            result = await asyncio.wait_for(_run(repo_url, audit_id, run_kind, steps), HARD_TIMEOUT_S)
        except Exception as exc:  # timeout or bug: keep the steps so far as a partial record
            steps.note("audit.crashed", f"{type(exc).__name__}: {str(exc)[:200]}", status="failed")
            db.update(audit_id, status="failed", error=type(exc).__name__, steps=steps.to_list())
            return
        db.update(audit_id, status="done", steps=result.get("steps", steps.to_list()), result=result,
                  # a non-cacheable result keeps no SHA, so the next request re-runs it
                  **({} if cacheable(result) else {"head_sha": None}))
