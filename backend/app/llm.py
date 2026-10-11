"""Groq chat client (OpenAI-compatible): model rotation, header-based scheduling, retries.

Groq limits are per model (per organisation): ~8k tokens/min, 1k requests/day and
200k tokens/day each on the free tier. So we rotate across GROQ_MODELS and schedule:

- QuotaPool tracks each model's remaining tokens/requests from the x-ratelimit-* response
  headers (captured by an httpx hook, so the neatlogs client wrapper stays intact) plus our
  own daily token count (the headers don't expose tokens-per-day).
- Before a call we estimate the tokens Groq will count (prompt + max_tokens) and pick a
  model that has room. If none has, we wait for the earliest reset instead of firing into
  a 429. 429s still happen (estimates are estimates); they put that model on cooldown and
  the next pick rotates to another model.
- Quick-phase calls are high priority: while one is in flight, deep-phase (low) calls
  leave QUICK_RESERVE tokens untouched on every model.
Every retry, rotation and wait is a recorded step and a neatlogs event.
"""
import asyncio
import json
import random
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
import openai

from app import config
from app import replay
from app.steps import StepLog
from app.tracing import event, span

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MAX_RETRIES = 2            # same-model retries for 5xx / timeouts / malformed tool calls
MAX_ATTEMPTS = 8           # total calls per chat() across all models
MAX_WAITS = 4              # scheduled waits for quota per chat()
BASE_DELAY = 1.0
MAX_DELAY = 20.0
DEFAULT_TPM = 8000
DEFAULT_TPD = int(config.env("GROQ_TPD", "200000"))
QUICK_RESERVE = 3500       # tokens per model kept free for quick audits while one runs
RESERVE_PCT = float(config.env("BUDGET_RESERVE_PCT", "25"))  # of each model's daily tokens, admin-only
PUBLIC_DAILY_TOKENS = int(config.env("PUBLIC_DAILY_TOKENS", "350000") or 0)  # all public traffic, per UTC day
CHARS_PER_TOKEN = 3.5      # measured ~4 on these models; a little conservative avoids 429s


class LLMError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class BudgetExhausted(Exception):
    """No allowed model has daily budget left. Deep audits wait for budget instead of
    degrading to a weaker model (deliberately not an LLMError, which means 'degrade')."""

    def __init__(self, retry_in_s: float | None, why: str):
        super().__init__(why)
        self.retry_in_s = retry_in_s


def judge_models() -> list[str]:
    """Models trusted to extract and judge claims (JUDGE_MODELS); empty means "all models"."""
    return [m.strip() for m in config.env("JUDGE_MODELS").split(",") if m.strip()]


def configured_models() -> list[str]:
    models = [m.strip() for m in config.env("GROQ_MODELS").split(",") if m.strip()]
    if not models:
        models = [m for m in (config.GROQ_MODEL, config.GROQ_FALLBACK_MODEL) if m]
    return list(dict.fromkeys(models))


def _duration(s: str | None) -> float | None:
    """Groq reset values look like '7.66s', '1m26.4s', '577ms', '2h3m1s'."""
    if not s:
        return None
    total, found = 0.0, False
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)(ms|h|m|s)", s):
        found = True
        total += float(num) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    return total if found else None


# ---------------------------------------------------------------- quota pool

@dataclass
class ModelQuota:
    model: str
    tpm_limit: int = DEFAULT_TPM
    tpm_remaining: float = DEFAULT_TPM
    tpm_reset_at: float = 0.0          # monotonic time when the minute window is full again
    rpd_remaining: int | None = None
    rpd_reset_at: float = 0.0
    tpd_limit: int = DEFAULT_TPD
    tpd_used: int = 0
    tpd_day: str = ""
    cooldown_until: float = 0.0        # after a 429 or repeated errors
    daily_blocked_until: float = 0.0   # after a TPD/RPD 429 (rolling 24h window)
    disabled: str | None = None        # e.g. model retired (404)
    calls: int = 0
    tokens: int = 0
    rate_limited: int = 0

    def available(self, now: float) -> float:
        return self.tpm_limit if now >= self.tpm_reset_at else self.tpm_remaining

    def blocked_until(self, now: float) -> float | None:
        """When this model can next be tried at all, or None if it can now."""
        if self.disabled:
            return float("inf")
        t = max(self.cooldown_until, self.daily_blocked_until,
                self.rpd_reset_at if self.rpd_remaining == 0 else 0)
        return t if t > now else None


class QuotaPool:
    def __init__(self, models: list[str] | None = None, clock=time.monotonic,
                 reserve_pct: float | None = None, public_cap: int | None = None):
        self.clock = clock
        # All public (non-reserve) traffic shares one daily token cap across models.
        self.public_cap = PUBLIC_DAILY_TOKENS if public_cap is None else public_cap
        self.public_used = 0
        self.public_day = ""
        self.persist_public = None  # callable(day, tokens) -> None; set by app.budget
        self.quotas: dict[str, ModelQuota] = {}
        self.order: list[str] = []
        self.quick_active = 0
        self.reserve_pct = RESERVE_PCT if reserve_pct is None else reserve_pct
        self.persist = None  # callable(model, ModelQuota) -> None; set by app.budget
        for m in models or []:
            self._q(m)

    def _q(self, model: str) -> ModelQuota:
        if model not in self.quotas:
            self.quotas[model] = ModelQuota(model)
            self.order.append(model)
        return self.quotas[model]

    def _roll_day(self, q: ModelQuota) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        if q.tpd_day != today:
            q.tpd_day, q.tpd_used = today, 0

    def _save(self, q: ModelQuota) -> None:
        if self.persist:
            try:
                self.persist(q.model, q)
            except Exception:
                pass  # budget bookkeeping must never break an audit

    def _roll_public(self) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        if self.public_day != today:
            self.public_day, self.public_used = today, 0

    def public_tokens_ok(self, est: int) -> bool:
        self._roll_public()
        return not self.public_cap or self.public_used + est <= self.public_cap

    def public_limit(self, q: ModelQuota) -> float:
        return q.tpd_limit * (1 - self.reserve_pct / 100)

    def daily_ok(self, model: str, est: int, use_reserve: bool = False) -> bool:
        """Does this model have daily budget for `est` tokens (public share unless use_reserve)?"""
        q, now = self._q(model), self.clock()
        self._roll_day(q)
        if q.disabled or q.daily_blocked_until > now:
            return False
        if not use_reserve and not self.public_tokens_ok(est):
            return False
        limit = q.tpd_limit if use_reserve else self.public_limit(q)
        if q.tpd_used + est > limit:
            # after Groq's rolling-window block passes, admin traffic may trust Groq again
            return use_reserve and q.daily_blocked_until != 0.0
        return True

    def daily_retry_in(self, models: list[str]) -> float | None:
        now = self.clock()
        waits = [self._q(m).daily_blocked_until - now for m in models if self._q(m).daily_blocked_until > now]
        return min(waits) if waits else None  # None: not until the daily counter resets

    def budget(self, models: list[str] | None = None, use_reserve: bool = False, est: int = 3000) -> dict:
        ms = models or self.order
        self._roll_public()
        return {"public_available": any(self.daily_ok(m, est, use_reserve) for m in ms),
                "public_tokens": {"used": self.public_used, "cap": self.public_cap},
                "models": {m: {"used": self._q(m).tpd_used, "limit": self._q(m).tpd_limit,
                               "public_limit": int(self.public_limit(self._q(m))),
                               "ok": self.daily_ok(m, est, use_reserve)} for m in ms}}

    @contextmanager
    def quick_window(self):
        """Mark a quick (high-priority) audit in flight, so deep calls leave it headroom."""
        self.quick_active += 1
        try:
            yield
        finally:
            self.quick_active -= 1

    def update_from_headers(self, model: str, headers) -> None:
        q, now = self._q(model), self.clock()
        try:
            if "x-ratelimit-limit-tokens" in headers:
                q.tpm_limit = int(float(headers["x-ratelimit-limit-tokens"]))
            if "x-ratelimit-remaining-tokens" in headers:
                q.tpm_remaining = float(headers["x-ratelimit-remaining-tokens"])
                q.tpm_reset_at = now + (_duration(headers.get("x-ratelimit-reset-tokens")) or 60)
            if "x-ratelimit-remaining-requests" in headers:
                q.rpd_remaining = int(float(headers["x-ratelimit-remaining-requests"]))
                q.rpd_reset_at = now + (_duration(headers.get("x-ratelimit-reset-requests")) or 3600)
        except (TypeError, ValueError):
            pass  # malformed header: keep the previous estimate

    def pick(self, models: list[str], est_tokens: int, priority: str = "high",
             exclude: set[str] = frozenset(), use_reserve: bool = False) -> tuple[str | None, float, str]:
        """-> (model, 0, why) if one has room now, else (None, seconds_to_wait, why)."""
        now = self.clock()
        reserve = QUICK_RESERVE if priority == "low" and self.quick_active > 0 else 0
        wake: list[float] = []
        reasons = []
        for m in models:
            q = self._q(m)
            self._roll_day(q)
            if m in exclude:
                continue
            blocked = q.blocked_until(now)
            if blocked is not None:
                wake.append(blocked)
                why = "disabled" if q.disabled else ("daily cap" if q.daily_blocked_until > now else "cooling down")
                reasons.append(f"{m}: {why}")
                continue
            if not self.daily_ok(m, est_tokens, use_reserve):
                reasons.append(f"{m}: daily token cap reached" if use_reserve
                               else f"{m}: daily public budget used ({self.reserve_pct:g}% kept in reserve)")
                continue
            if q.available(now) >= est_tokens + reserve:
                q.tpm_remaining = q.available(now) - est_tokens  # optimistic, until headers arrive
                if now >= q.tpm_reset_at:
                    q.tpm_reset_at = now + 60
                return m, 0.0, f"{int(q.tpm_remaining)} tokens left this minute"
            wake.append(q.tpm_reset_at)
            reasons.append(f"{m}: {int(q.available(now))} tokens left, need {est_tokens + reserve}")
        finite = [w for w in wake if w != float("inf")]
        if not finite:
            return None, float("inf"), "; ".join(reasons) or "no models"
        return None, max(0.2, min(finite) - now), "; ".join(reasons)

    def record(self, model: str, tokens: int, public: bool = True) -> None:
        q = self._q(model)
        self._roll_day(q)
        q.calls += 1
        q.tokens += tokens
        q.tpd_used += tokens
        self._save(q)
        if public:
            self._roll_public()
            self.public_used += tokens
            if self.persist_public:
                try:
                    self.persist_public(self.public_day, tokens)
                except Exception:
                    pass

    def cooldown(self, model: str, seconds: float, rate_limited: bool = True) -> None:
        q = self._q(model)
        q.cooldown_until = max(q.cooldown_until, self.clock() + seconds)
        if rate_limited:
            q.rate_limited += 1
            q.tpm_remaining = 0
            q.tpm_reset_at = max(q.tpm_reset_at, self.clock() + seconds)

    def mark_daily(self, model: str, daily: dict, retry_after: float) -> None:
        """A daily cap was hit: record Groq's numbers and keep the model out until it frees up."""
        q = self._q(model)
        self._roll_day(q)
        if daily["kind"] == "TPD":
            q.tpd_limit, q.tpd_used = daily["limit"], max(q.tpd_used, daily["used"])
        q.daily_blocked_until = self.clock() + retry_after
        q.rate_limited += 1
        self._save(q)

    def disable(self, model: str, reason: str) -> None:
        self._q(model).disabled = reason

    def snapshot(self) -> dict:
        now = self.clock()
        return {m: {"tpm_available": int(q.available(now)), "tpm_limit": q.tpm_limit,
                    "rpd_remaining": q.rpd_remaining, "tpd_used": q.tpd_used, "tpd_limit": q.tpd_limit,
                    "calls": q.calls, "tokens": q.tokens, "rate_limited": q.rate_limited,
                    "daily_blocked_s": max(0, round(q.daily_blocked_until - now)),
                    "disabled": q.disabled}
                for m, q in self.quotas.items()}


POOL = QuotaPool()  # shared by every audit in the process (quick and deep workers)


# ---------------------------------------------------------------- client

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


def _header_hook(pool: QuotaPool):
    async def hook(response: httpx.Response) -> None:
        try:
            model = json.loads(response.request.content or b"{}").get("model")
        except (ValueError, AttributeError):
            return
        if model:
            pool.update_from_headers(model, response.headers)
    return hook


def make_client(timeout: float = 30.0, pool: QuotaPool | None = None) -> openai.AsyncOpenAI:
    http = httpx.AsyncClient(timeout=timeout,
                             event_hooks={"response": [_header_hook(pool or POOL)]})
    client = openai.AsyncOpenAI(
        api_key=config.GROQ_API_KEY or "missing",
        base_url=GROQ_BASE_URL,
        max_retries=0,  # retries are ours, so they are visible as steps
        timeout=timeout,
        http_client=http,
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


_DAILY_RX = re.compile(r"(tokens|requests) per day \((TPD|RPD)\): Limit (\d+), Used (\d+)")


def _daily_limit(exc: Exception) -> dict | None:
    """Parse 'on tokens per day (TPD): Limit 200000, Used 198813' from a Groq 429."""
    m = _DAILY_RX.search(str(getattr(exc, "body", None) or exc))
    if not m:
        return None
    return {"kind": m.group(2), "limit": int(m.group(3)), "used": int(m.group(4))}


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


def estimate_tokens(messages: list[dict], tools: list | None, max_tokens: int) -> int:
    chars = len(json.dumps(messages, ensure_ascii=False)) + (len(json.dumps(tools)) if tools else 0)
    return int(chars / CHARS_PER_TOKEN) + max_tokens


class LLM:
    def __init__(
        self,
        steps: StepLog,
        client=None,
        models: list[str] | None = None,
        deadline: float | None = None,
        sleep=asyncio.sleep,
        max_retries: int = MAX_RETRIES,
        pool: QuotaPool | None = None,
        priority: str = "high",
        use_reserve: bool = False,
        # backwards-compatible names
        model: str | None = None,
        fallback_model: str | None = None,
    ):
        self.steps = steps
        self.pool = pool or POOL
        self.client = client or make_client(pool=self.pool)
        self.models = models or ([m for m in (model, fallback_model) if m] or configured_models())
        self.deadline = deadline
        self.sleep = sleep
        self.max_retries = max_retries
        self.priority = priority
        self.use_reserve = use_reserve       # admin requests may spend the reserved budget
        self.usage = Usage()
        self._judging: list[str] | None = None

    @contextmanager
    def judging(self, models: list[str] | None = None):
        """Claim extraction/judging: only JUDGE_MODELS, and wait for budget rather than degrade."""
        prev = self._judging
        self._judging = models or judge_models() or self.models
        try:
            yield
        finally:
            self._judging = prev

    def _remaining(self) -> float:
        return float("inf") if self.deadline is None else self.deadline - time.monotonic()

    @span("CHAIN", "llm.chat")
    async def chat(self, purpose: str, messages: list[dict], *, tools: list | None = None,
                   tool_choice: str | None = None, json_mode: bool = False,
                   max_tokens: int = 1500, prefer: list[str] | None = None):
        """Return the assistant message. Raises LLMError only when no model can answer in time.

        `prefer` reorders the models for this call (e.g. one that makes parallel tool calls).
        """
        if replay.mode() == "replay":
            return self._replay(purpose, messages, tools)
        if not self.models:
            raise LLMError("not_configured", "no GROQ_MODELS configured")
        allowed = self._judging or self.models
        order = sorted(allowed, key=lambda m: prefer.index(m) if prefer and m in prefer else 99)
        est = estimate_tokens(messages, tools, max_tokens)
        last_kind, last_model, attempts, waits = "unknown", None, 0, 0
        same_model_retries = {}

        while attempts < MAX_ATTEMPTS:
            if self._remaining() <= 1:
                raise LLMError("timeout", "audit time budget exhausted before LLM call")
            if self._judging and not any(self.pool.daily_ok(m, est, self.use_reserve) for m in order):
                raise BudgetExhausted(self.pool.daily_retry_in(order),
                                      f"no judge model has daily budget ({', '.join(order)})")
            model, wait, why = self.pool.pick(order, est, self.priority, use_reserve=self.use_reserve)
            if model is None:
                if wait == float("inf"):
                    raise LLMError("daily_quota" if "daily" in why else last_kind,
                                   f"no model available: {why}")
                if wait >= self._remaining() - 5:
                    raise LLMError("rate_limited", f"quota resets in {wait:.0f}s, past the time budget")
                waits += 1
                if waits > MAX_WAITS:
                    raise LLMError("rate_limited", f"still no quota after {MAX_WAITS} waits ({why})")
                self.steps.note(f"llm.{purpose}.wait_for_quota",
                                f"waiting {wait:.1f}s for quota ({why})", wait_s=round(wait, 1))
                event("waiting {wait}s for model quota", level="info", wait=round(wait, 1), why=why)
                await self.sleep(wait)
                continue
            if last_model is not None and model != last_model:
                self.steps.note(f"llm.{purpose}.fallback", f"switching to model {model}",
                                model=model, after=last_kind)
                event("llm fallback to {model}", level="warning", model=model, purpose=purpose)
            last_model = model
            attempts += 1

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
                s.data.update(model=model, est_tokens=est, scheduled=why)
                try:
                    resp = await self.client.chat.completions.create(**kwargs)
                except Exception as exc:
                    last_kind = await self._on_failure(s, model, exc, same_model_retries)
                    resp = None
                if resp is not None:
                    self.usage.add(model, resp.usage)
                    if replay.mode() == "record":
                        replay.record(purpose, resp.choices[0].message, resp.usage)
                    tokens = getattr(resp.usage, "total_tokens", 0) or 0
                    self.pool.record(model, tokens, public=not self.use_reserve)
                    s.detail = f"{model} ok"
                    s.data["tokens"] = tokens
                    s.data["latency_ms"] = int((time.perf_counter() - started) * 1000)
                    return resp.choices[0].message
        raise LLMError(last_kind, f"gave up after {attempts} attempts ({last_kind})")

    async def _on_failure(self, s, model: str, exc: Exception, retries: dict[str, int]) -> str:
        """Record a failed call and decide how the pool treats the model. Returns the error kind."""
        kind, retryable = _classify(exc)
        self.usage.failed_calls += 1
        s.status, s.error_kind = "failed", kind
        s.detail = f"{model}: {str(exc)[:400]}"
        event("llm call failed: {kind}", level="warning", kind=kind, model=model)
        if kind == "rate_limited":
            daily = _daily_limit(exc)
            if daily:
                # TPD/RPD isn't in the headers; Groq's 429 text is the only signal. Rolling window:
                # the model is usable again after retry-after.
                self.pool.mark_daily(model, daily, _retry_after(exc) or 300)
                s.error_kind = f"rate_limited_{daily['kind'].lower()}"
                event("model hit its daily {limit} cap", level="warning", limit=daily["kind"], model=model)
            else:
                self.pool.cooldown(model, _retry_after(exc) or 10)  # next pick rotates
        elif kind == "model_not_found":
            self.pool.disable(model, kind)                       # retired model: stop using it
        elif not retryable:
            self.pool.cooldown(model, 30, rate_limited=False)
        else:
            n = retries[model] = retries.get(model, 0) + 1
            if n > self.max_retries:
                self.pool.cooldown(model, 15, rate_limited=False)  # rotate away
            else:
                delay = min(BASE_DELAY * 2 ** (n - 1) + random.random() * 0.3, MAX_DELAY)  # noqa: S311 (jitter)
                if delay < self._remaining() - 2:
                    s.data["retry_in_s"] = round(delay, 2)
                    event("llm retry in {delay}s", level="info", delay=round(delay, 2), model=model)
                    await self.sleep(delay)
        return kind

    def _replay(self, purpose: str, messages: list[dict], tools: list | None):
        """LLM_MODE=replay: answer from fixtures, no network, no quota spent."""
        miss = None
        with self.steps.step(f"llm.{purpose}") as s:
            s.data["model"] = "replay"
            try:
                message, usage = replay.respond(purpose, messages, tools)
            except replay.ReplayMiss as exc:
                s.status, s.error_kind, s.detail = "failed", "replay_miss", str(exc)
                miss = exc
            else:
                self.usage.add("replay", usage)
                s.data["tokens"] = usage.total_tokens
                s.detail = "replayed from fixture"
        if miss is not None:  # raised outside the step: StepLog.step() swallows exceptions
            raise LLMError("replay_miss", str(miss))
        return message
