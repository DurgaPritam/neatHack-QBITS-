"""Groq chat client (OpenAI-compatible) with retries, fallback model and usage tracking.

Reliability policy:
- 429 / 5xx / timeouts / connection errors: exponential backoff, honouring retry-after.
- After MAX_RETRIES on a model (or a non-retryable error like a retired model),
  switch to GROQ_FALLBACK_MODEL.
- A model that returned 429 is put on cooldown so later calls in the same audit
  go straight to the fallback instead of waiting again.
Every retry and fallback is a recorded step and a neatlogs event.
"""
import asyncio
import random
import time
from dataclasses import dataclass, field

import openai

from app import config
from app.steps import StepLog
from app.tracing import event, span

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MAX_RETRIES = 2
RATE_LIMIT_RETRIES = 1   # fallback model has its own quota, so don't wait long on a 429
MAX_RATE_LIMIT_WAIT = 15.0
MAX_ROUNDS = 3           # rounds over [primary, fallback] when every model is rate-limited
BASE_DELAY = 1.0
MAX_DELAY = 20.0


class LLMError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    failed_calls: int = 0
    by_model: dict[str, dict[str, int]] = field(default_factory=dict)

    def add(self, model: str, usage) -> None:
        p = getattr(usage, "prompt_tokens", 0) or 0
        c = getattr(usage, "completion_tokens", 0) or 0
        self.prompt_tokens += p
        self.completion_tokens += c
        self.calls += 1
        m = self.by_model.setdefault(model, {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0})
        m["prompt_tokens"] += p
        m["completion_tokens"] += c
        m["calls"] += 1

    def to_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
            "calls": self.calls,
            "failed_calls": self.failed_calls,
            "by_model": self.by_model,
        }


def make_client(timeout: float = 30.0) -> openai.AsyncOpenAI:
    client = openai.AsyncOpenAI(
        api_key=config.GROQ_API_KEY or "missing",
        base_url=GROQ_BASE_URL,
        max_retries=0,  # retries are ours, so they are visible as steps
        timeout=timeout,
    )
    try:
        import neatlogs

        from app import tracing

        if tracing._enabled:
            client = neatlogs.wrap(client)  # every completion becomes an LLM span
    except Exception:
        pass
    return client


def _retry_after(exc: Exception) -> float | None:
    resp = getattr(exc, "response", None)
    if resp is None:
        return None
    raw = resp.headers.get("retry-after")
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def _classify(exc: Exception) -> tuple[str, bool]:
    """-> (error_kind, retryable)"""
    if isinstance(exc, openai.RateLimitError):
        return "rate_limited", True
    if isinstance(exc, openai.APITimeoutError):
        return "timeout", True
    if isinstance(exc, openai.APIConnectionError):
        return "connection", True
    if isinstance(exc, openai.APIStatusError):
        if exc.status_code >= 500:
            return f"http_{exc.status_code}", True
        if exc.status_code == 404:
            return "model_not_found", False
        if exc.status_code == 400 and "tool_use_failed" in str(exc):
            return "tool_use_failed", True  # model emitted a malformed tool call; try again
        return f"http_{exc.status_code}", False
    return type(exc).__name__, False


def _reasoning_params(model: str) -> dict:
    """Keep hidden reasoning short: it counts against the 8k tokens-per-minute quota."""
    if model.startswith("openai/gpt-oss"):
        return {"reasoning_effort": "low"}
    if model.startswith("qwen/qwen3"):
        return {"reasoning_effort": "none"}
    return {}


class LLM:
    def __init__(
        self,
        steps: StepLog,
        client=None,
        model: str | None = None,
        fallback_model: str | None = None,
        deadline: float | None = None,
        sleep=asyncio.sleep,
        max_retries: int = MAX_RETRIES,
    ):
        self.steps = steps
        self.client = client or make_client()
        self.models = [m for m in (model or config.GROQ_MODEL, fallback_model or config.GROQ_FALLBACK_MODEL) if m]
        self.deadline = deadline
        self.sleep = sleep
        self.max_retries = max_retries
        self.usage = Usage()
        self._cooldown: dict[str, float] = {}

    def _remaining(self) -> float:
        return float("inf") if self.deadline is None else self.deadline - time.monotonic()

    def _model_order(self) -> list[str]:
        now = time.monotonic()
        ready = [m for m in self.models if self._cooldown.get(m, 0) <= now]
        cooling = [m for m in self.models if m not in ready]
        return ready + cooling

    @span("CHAIN", "llm.chat")
    async def chat(self, purpose: str, messages: list[dict], *, tools: list | None = None,
                   tool_choice: str | None = None, json_mode: bool = False,
                   max_tokens: int = 1500):
        """Return the assistant message. Raises LLMError only when every model failed.

        If every model is rate-limited and the time budget allows, wait for the earliest
        quota reset and go round again (Groq resets are usually a few seconds away).
        """
        if not self.models:
            raise LLMError("not_configured", "GROQ_MODEL is not set")
        for rnd in range(MAX_ROUNDS):
            try:
                return await self._one_round(purpose, messages, tools, tool_choice, json_mode,
                                             max_tokens, first_round=rnd == 0)
            except LLMError as exc:
                if exc.kind != "rate_limited" or rnd == MAX_ROUNDS - 1:
                    raise
                wait = max(0.5, min(self._cooldown.values(), default=0) - time.monotonic())
                if wait >= self._remaining() - 5:
                    raise
                self.steps.note(f"llm.{purpose}.wait_for_quota",
                                f"all models rate-limited; waiting {wait:.1f}s for quota reset",
                                wait_s=round(wait, 1))
                event("all models rate-limited; waiting {wait}s", level="warning", wait=round(wait, 1))
                await self.sleep(wait)
        raise LLMError("rate_limited", "unreachable")

    async def _one_round(self, purpose, messages, tools, tool_choice, json_mode, max_tokens,
                         first_round: bool):
        last_kind = "unknown"
        for i, model in enumerate(self._model_order()):
            if i > 0 or not first_round:
                self.steps.note(f"llm.{purpose}.fallback", f"switching to model {model}",
                                model=model, after=last_kind)
                event("llm fallback to {model}", level="warning", model=model, purpose=purpose)
            for attempt in range(self.max_retries + 1):
                if self._remaining() <= 1:
                    raise LLMError("timeout", "audit time budget exhausted before LLM call")
                kwargs = dict(model=model, messages=messages, max_tokens=max_tokens, temperature=0.2)
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = tool_choice or "auto"
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                extra = _reasoning_params(model)
                if extra:
                    kwargs["extra_body"] = extra
                started = time.perf_counter()
                with self.steps.step(f"llm.{purpose}") as s:
                    s.data["model"] = model
                    try:
                        resp = await self.client.chat.completions.create(**kwargs)
                    except Exception as exc:
                        kind, retryable = _classify(exc)
                        last_kind = kind
                        self.usage.failed_calls += 1
                        s.status, s.error_kind = "failed", kind
                        s.detail = f"{model}: {str(exc)[:400]}"
                        event("llm call failed: {kind}", level="warning", kind=kind, model=model,
                              purpose=purpose, attempt=attempt)
                        wait = _retry_after(exc)
                        if kind == "rate_limited":
                            self._cooldown[model] = time.monotonic() + (wait or 10)
                        limit = min(self.max_retries, RATE_LIMIT_RETRIES) if kind == "rate_limited" else self.max_retries
                        if not retryable or attempt >= limit:
                            break  # out of the step; try next model
                        if kind == "rate_limited" and wait is not None and wait > MAX_RATE_LIMIT_WAIT:
                            break  # long reset: the fallback model is the faster path
                        delay = min(wait if wait is not None else BASE_DELAY * 2 ** attempt + random.random() * 0.3,
                                    MAX_DELAY)
                        if delay >= self._remaining() - 2:
                            break  # no time to wait; go to fallback
                        s.data["retry_in_s"] = round(delay, 2)
                        event("llm retry in {delay}s", level="info", delay=round(delay, 2), model=model)
                        await self.sleep(delay)
                        continue
                    self.usage.add(model, resp.usage)
                    s.detail = f"{model} ok"
                    s.data["tokens"] = getattr(resp.usage, "total_tokens", None)
                    s.data["latency_ms"] = int((time.perf_counter() - started) * 1000)
                    return resp.choices[0].message
                # reached only via `break` inside the step on a terminal failure for this model
                break
        raise LLMError(last_kind, f"all models failed ({last_kind})")
