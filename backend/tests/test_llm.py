import asyncio

import pytest

from app.llm import LLM, LLMError
from app.steps import StepLog
from tests.fakes import FakeGroq, model_gone, msg, no_sleep, rate_limit, server_error


def make(script, sleeps=None):
    async def sleep(s):
        if sleeps is not None:
            sleeps.append(s)

    log = StepLog()
    fake = FakeGroq(script)
    return LLM(log, client=fake, model="primary", fallback_model="backup", sleep=sleep), fake, log


def test_backoff_respects_retry_after_then_succeeds():
    sleeps = []
    llm, fake, log = make([rate_limit("3"), msg("hi")], sleeps)
    out = asyncio.run(llm.chat("t", [{"role": "user", "content": "x"}]))
    assert out.content == "hi"
    assert sleeps == [3.0]
    assert [c["model"] for c in fake.calls] == ["primary", "primary"]
    assert llm.usage.calls == 1 and llm.usage.failed_calls == 1


def test_exponential_backoff_without_retry_after_then_fallback():
    sleeps = []
    llm, fake, log = make([server_error(), server_error(), server_error(), msg("from backup")], sleeps)
    out = asyncio.run(llm.chat("t", [{"role": "user", "content": "x"}]))
    assert out.content == "from backup"
    assert [c["model"] for c in fake.calls] == ["primary"] * 3 + ["backup"]
    assert len(sleeps) == 2 and sleeps[1] > sleeps[0]  # exponential
    names = [s.name for s in log.steps]
    assert "llm.t.fallback" in names
    assert llm.usage.by_model["backup"]["calls"] == 1


def test_non_retryable_goes_straight_to_fallback():
    llm, fake, log = make([model_gone(), msg("ok")])
    asyncio.run(llm.chat("t", [{"role": "user", "content": "x"}]))
    assert [c["model"] for c in fake.calls] == ["primary", "backup"]


def test_long_rate_limit_switches_immediately_and_cools_down():
    sleeps = []
    llm, fake, _ = make([rate_limit("30"), msg("a"), msg("b")], sleeps)
    asyncio.run(llm.chat("t", [{"role": "user", "content": "x"}]))
    asyncio.run(llm.chat("t", [{"role": "user", "content": "x"}]))
    assert sleeps == []  # a 30s reset isn't worth waiting for when a fallback exists
    # second call skips the primary while it cools down
    assert [c["model"] for c in fake.calls] == ["primary", "backup", "backup"]


def test_all_models_fail_raises():
    llm, _, log = make(lambda kw: server_error())
    with pytest.raises(LLMError):
        asyncio.run(llm.chat("t", [{"role": "user", "content": "x"}]))
    assert all(s.status == "failed" for s in log.steps if s.name == "llm.t")


def test_waits_for_quota_reset_when_all_models_rate_limited():
    sleeps = []
    llm, fake, log = make([rate_limit("30"), rate_limit("30"), msg("after wait")], sleeps)
    out = asyncio.run(llm.chat("t", [{"role": "user", "content": "x"}]))
    assert out.content == "after wait"
    assert len(sleeps) == 1 and 25 < sleeps[0] <= 30
    assert "llm.t.wait_for_quota" in [s.name for s in log.steps]


def test_gives_up_when_quota_reset_exceeds_time_budget():
    import time as _t
    llm, fake, log = make([rate_limit("30"), rate_limit("30")])
    llm.deadline = _t.monotonic() + 10
    with pytest.raises(LLMError):
        asyncio.run(llm.chat("t", [{"role": "user", "content": "x"}]))
