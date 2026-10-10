import asyncio
import time

import pytest

from app.llm import LLM, LLMError, QuotaPool, _duration, configured_models
from app.steps import StepLog
from tests.fakes import FakeGroq, model_gone, msg, rate_limit, server_error


class Clock:
    """Fake monotonic clock; the LLM's sleep advances it."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(script, models=("primary", "backup"), deadline=None):
    clock = Clock()
    sleeps = []

    async def sleep(s):
        sleeps.append(s)
        clock.t += s

    log = StepLog()
    fake = FakeGroq(script)
    pool = QuotaPool(list(models), clock=clock)
    llm = LLM(log, client=fake, models=list(models), sleep=sleep, pool=pool, deadline=deadline)
    llm._remaining = lambda: float("inf") if deadline is None else deadline - clock.t
    return llm, fake, log, pool, sleeps, clock


def run(llm, **kw):
    return asyncio.run(llm.chat("t", [{"role": "user", "content": "x"}], max_tokens=100, **kw))


def test_parse_groq_durations():
    assert _duration("7.66s") == pytest.approx(7.66)
    assert _duration("1m26.4s") == pytest.approx(86.4)
    assert _duration("577ms") == pytest.approx(0.577)
    assert _duration(None) is None and _duration("soon") is None


def test_rate_limit_rotates_to_next_model_without_waiting():
    llm, fake, log, pool, sleeps, _ = make([rate_limit("3"), msg("hi")])
    assert run(llm).content == "hi"
    assert [c["model"] for c in fake.calls] == ["primary", "backup"]
    assert sleeps == []
    assert "llm.t.fallback" in [s.name for s in log.steps]
    assert pool.quotas["primary"].rate_limited == 1


def test_exponential_backoff_on_server_errors_then_rotate():
    llm, fake, log, pool, sleeps, _ = make([server_error(), server_error(), server_error(), msg("ok")])
    assert run(llm).content == "ok"
    assert [c["model"] for c in fake.calls] == ["primary"] * 3 + ["backup"]
    assert len(sleeps) == 2 and sleeps[1] > sleeps[0]


def test_retired_model_is_disabled():
    llm, fake, _, pool, _, _ = make([model_gone(), msg("ok"), msg("ok2")])
    run(llm)
    run(llm)
    assert [c["model"] for c in fake.calls] == ["primary", "backup", "backup"]
    assert pool.quotas["primary"].disabled == "model_not_found"


def test_headers_schedule_calls_before_a_429():
    """Primary's headers say it's out of tokens: pick backup without ever calling primary."""
    llm, fake, log, pool, sleeps, _ = make([msg("from backup")])
    pool.update_from_headers("primary", {"x-ratelimit-limit-tokens": "8000",
                                         "x-ratelimit-remaining-tokens": "50",
                                         "x-ratelimit-reset-tokens": "40s"})
    run(llm)
    assert [c["model"] for c in fake.calls] == ["backup"]


def test_waits_for_earliest_reset_when_every_model_is_low():
    llm, fake, log, pool, sleeps, clock = make([msg("after wait")])
    for m, reset in (("primary", "12s"), ("backup", "5s")):
        pool.update_from_headers(m, {"x-ratelimit-remaining-tokens": "10", "x-ratelimit-reset-tokens": reset})
    assert run(llm).content == "after wait"
    assert sleeps == [pytest.approx(5.0)]
    assert fake.calls[0]["model"] == "backup"
    assert "llm.t.wait_for_quota" in [s.name for s in log.steps]


def test_gives_up_when_reset_is_past_the_deadline():
    llm, _, _, pool, _, clock = make([msg("never")], deadline=None)
    for m in ("primary", "backup"):
        pool.update_from_headers(m, {"x-ratelimit-remaining-tokens": "0", "x-ratelimit-reset-tokens": "50s"})
    llm._remaining = lambda: 20
    with pytest.raises(LLMError) as e:
        run(llm)
    assert e.value.kind == "rate_limited"


def test_low_priority_leaves_headroom_for_quick_audits():
    llm, fake, _, pool, sleeps, _ = make([msg("deep")])
    llm.priority = "low"
    for m in ("primary", "backup"):
        pool.update_from_headers(m, {"x-ratelimit-remaining-tokens": "2000", "x-ratelimit-reset-tokens": "6s"})
    with pool.quick_window():
        run(llm)
    assert sleeps and sleeps[0] == pytest.approx(6.0)  # waited instead of eating the reserve
    llm2, fake2, _, pool2, sleeps2, _ = make([msg("quick")])
    pool2.update_from_headers("primary", {"x-ratelimit-remaining-tokens": "2000", "x-ratelimit-reset-tokens": "6s"})
    with pool2.quick_window():
        run(llm2)  # high priority uses it straight away
    assert sleeps2 == [] and fake2.calls[0]["model"] == "primary"


def test_daily_token_cap_is_tracked():
    llm, _, _, pool, _, _ = make([msg("a")], models=("only",))
    pool.quotas["only"].tpd_limit = 100
    pool.record("only", 90)
    with pytest.raises(LLMError) as e:
        run(llm)
    assert e.value.kind == "daily_quota"


def test_all_models_failing_raises_and_records():
    llm, _, log, _, _, _ = make(lambda kw: server_error())
    with pytest.raises(LLMError):
        run(llm)
    assert all(s.status == "failed" for s in log.steps if s.name == "llm.t")


def test_prefer_reorders_models():
    llm, fake, *_ = make([msg("x")])
    run(llm, prefer=["backup"])
    assert fake.calls[0]["model"] == "backup"


def test_models_from_env(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "env", lambda k, d="": "a, b ,a" if k == "GROQ_MODELS" else d)
    assert configured_models() == ["a", "b"]


def test_usage_and_pool_accounting():
    llm, _, _, pool, _, _ = make([msg("x", tokens=(300, 50))])
    run(llm)
    assert llm.usage.to_dict()["total_tokens"] == 350
    assert pool.snapshot()["primary"]["tokens"] == 350
    assert time.monotonic()  # sanity: real clock untouched
