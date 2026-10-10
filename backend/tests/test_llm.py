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


def test_rate_limited_model_cools_down_for_next_call():
    llm, fake, _ = make([rate_limit("30"), rate_limit("30"), rate_limit("30"), msg("a"), msg("b")])
    asyncio.run(llm.chat("t", [{"role": "user", "content": "x"}]))
    asyncio.run(llm.chat("t", [{"role": "user", "content": "x"}]))
    assert fake.calls[-1]["model"] == "backup"  # primary skipped while cooling down


def test_all_models_fail_raises():
    llm, _, log = make(lambda kw: server_error())
    with pytest.raises(LLMError):
        asyncio.run(llm.chat("t", [{"role": "user", "content": "x"}]))
    assert all(s.status == "failed" for s in log.steps if s.name == "llm.t")
