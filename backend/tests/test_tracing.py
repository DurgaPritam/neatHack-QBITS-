"""Tests must never send traces: no exporter may be bootstrapped, even by the SDK on its own."""
import asyncio
import os

import httpx
from neatlogs import _wrap_utils

from app import config, tracing
from app.audit import run_deterministic_audit


def test_key_is_absent_for_the_sdk():
    assert os.environ.get("NEATLOGS_API_KEY", "") == ""
    assert config.NEATLOGS_API_KEY == ""
    assert tracing.init_tracing() is False
    assert tracing._enabled is False


def test_span_decorated_code_runs_untraced_when_tracing_is_off(monkeypatch):
    # Even if a key reaches os.environ later, decorated functions must not touch the SDK.
    monkeypatch.setenv("NEATLOGS_API_KEY", "not-a-real-key")

    @tracing.span("TOOL", "test.sync")
    def sync_fn(x):
        return x + 1

    @tracing.span("TOOL", "test.async")
    async def async_fn(x):
        return x * 2

    assert sync_fn(1) == 2
    assert asyncio.run(async_fn(3)) == 6
    assert _wrap_utils._wrapper_bootstrapped is False
    assert _wrap_utils.get_neatlogs_provider() is None


def test_an_audit_bootstraps_no_exporter():
    def handler(req: httpx.Request):
        return httpx.Response(404, json={"message": "Not Found"})

    asyncio.run(run_deterministic_audit("https://github.com/acme/demo", token="",
                                        transport=httpx.MockTransport(handler)))
    assert _wrap_utils._wrapper_bootstrapped is False
    assert _wrap_utils.get_neatlogs_provider() is None
