"""Step log: every action the auditor takes, including failures, is recorded here.

Failures are first-class — they are evidence the agent recovers, not crashes.
"""
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, Callable


@dataclass
class Step:
    name: str
    status: str = "ok"  # ok | failed | skipped
    detail: str = ""
    error_kind: str | None = None
    duration_ms: int = 0
    data: dict[str, Any] = field(default_factory=dict)


class StepLog:
    def __init__(self, on_change: Callable[["StepLog"], None] | None = None) -> None:
        self.steps: list[Step] = []
        self.on_change = on_change  # e.g. persist progress so the UI can show a live log

    def _append(self, step: Step) -> None:
        self.steps.append(step)
        if self.on_change:
            try:
                self.on_change(self)
            except Exception:
                pass  # progress reporting must never break an audit

    @contextmanager
    def step(self, name: str):
        """Time a step. Exceptions are recorded and swallowed so the audit continues."""
        s = Step(name=name)
        start = time.perf_counter()
        try:
            yield s
        except Exception as exc:
            s.status = "failed"
            s.error_kind = getattr(exc, "kind", type(exc).__name__)
            s.detail = str(exc)[:300]
        finally:
            s.duration_ms = int((time.perf_counter() - start) * 1000)
            self._append(s)

    def skip(self, name: str, reason: str) -> None:
        self.note(name, reason, status="skipped")

    def note(self, name: str, detail: str, status: str = "ok", **data: Any) -> None:
        """Record an instantaneous step (a decision, fallback, or skip)."""
        self._append(Step(name=name, status=status, detail=detail, data=data))

    def to_list(self) -> list[dict[str, Any]]:
        return [asdict(s) for s in self.steps]
