"""Record / replay of LLM responses, so the app and tests run without spending Groq tokens.

LLM_MODE=live    (default) real Groq calls
LLM_MODE=record  real calls, and each response is saved under fixtures/llm/<owner>__<repo>.json
LLM_MODE=replay  no network for the LLM: answers come from those fixtures; a repo without a
                 fixture behaves like an LLM outage (template verdict, honestly labelled)

Fixtures are keyed by repo and purpose (quick_verdict, claims, verify, verdict). Replayed
claim evidence still goes through grounding: the replayed verify turn asks to read the cited
files from the real repo, so nothing "verified" is taken on trust from the fixture.
"""
import contextvars
import json
import re
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from app import config

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "llm"
_repo: contextvars.ContextVar[str | None] = contextvars.ContextVar("replay_repo", default=None)


class ReplayMiss(Exception):
    """No fixture for this repo/purpose."""


def mode() -> str:
    m = config.env("LLM_MODE", "live").lower()
    return m if m in ("live", "replay", "record") else "live"


@contextmanager
def repo_context(full_name: str | None):
    token = _repo.set((full_name or "").lower() or None)
    try:
        yield
    finally:
        _repo.reset(token)


def current_repo() -> str | None:
    return _repo.get()


def fixture_path(repo: str) -> Path:
    return FIXTURE_DIR / (re.sub(r"[^a-z0-9._-]+", "__", repo.lower()) + ".json")


def load(repo: str | None) -> dict | None:
    if not repo:
        return None
    p = fixture_path(repo)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def _base(purpose: str) -> str:
    return purpose.split(".")[0]


def _message(content=None, tool_calls=None, tokens: int = 0):
    calls = None
    if tool_calls:
        calls = [SimpleNamespace(id=f"replay_{i}", type="function",
                                 function=SimpleNamespace(name=c["name"], arguments=json.dumps(c["arguments"])))
                 for i, c in enumerate(tool_calls)]
    msg = SimpleNamespace(role="assistant", content=json.dumps(content) if isinstance(content, (dict, list)) else content,
                          tool_calls=calls)
    usage = SimpleNamespace(prompt_tokens=int(tokens * 0.85), completion_tokens=tokens - int(tokens * 0.85),
                            total_tokens=tokens)
    return msg, usage


def respond(purpose: str, messages: list[dict], tools: list | None):
    """-> (message, usage) for this purpose, or ReplayMiss."""
    fx = load(current_repo())
    if fx is None:
        raise ReplayMiss(f"no LLM fixture for {current_repo() or 'unknown repo'}")
    responses, usage = fx.get("responses", {}), fx.get("usage", {})
    base = _base(purpose)
    tokens = int(usage.get(base, 0))
    if purpose.endswith("roast_retry"):
        verdict = responses.get(base) or {}
        if "roast" not in verdict:
            raise ReplayMiss(f"no roast for {purpose}")
        return _message({"roast": verdict["roast"]}, tokens=tokens)
    if base == "verify":
        already_used_tools = any(m.get("role") == "tool" for m in messages)
        if tools and not already_used_tools and fx.get("verify_tool_calls"):
            return _message(tool_calls=fx["verify_tool_calls"], tokens=tokens)
    if base not in responses:
        raise ReplayMiss(f"no {base} response in fixture for {current_repo()}")
    return _message(responses[base], tokens=tokens)


def record(purpose: str, message, usage) -> None:
    """LLM_MODE=record: keep the first response per purpose for this repo."""
    repo = current_repo()
    if not repo:
        return
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    p = fixture_path(repo)
    fx = json.loads(p.read_text()) if p.exists() else {"repo": repo, "source": "recorded (LLM_MODE=record)",
                                                       "responses": {}, "usage": {}}
    base = _base(purpose)
    if message.tool_calls:
        if base == "verify" and "verify_tool_calls" not in fx:
            fx["verify_tool_calls"] = [{"name": c.function.name, "arguments": json.loads(c.function.arguments or "{}")}
                                       for c in message.tool_calls]
    elif base not in fx["responses"] and message.content:
        try:
            fx["responses"][base] = json.loads(message.content)
        except ValueError:
            return
        fx["usage"][base] = getattr(usage, "total_tokens", 0) or 0
    p.write_text(json.dumps(fx, indent=2, ensure_ascii=False))
