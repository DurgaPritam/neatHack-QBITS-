"""A scripted stand-in for the Groq/OpenAI client. No network."""
import json
from types import SimpleNamespace

import httpx
import openai


def rate_limit(retry_after: str | None = "1"):
    headers = {"retry-after": retry_after} if retry_after else {}
    resp = httpx.Response(429, headers=headers,
                          request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"))
    return openai.RateLimitError("rate limited", response=resp, body=None)


def server_error(code: int = 503):
    resp = httpx.Response(code, request=httpx.Request("POST", "https://api.groq.com/x"))
    return openai.InternalServerError("boom", response=resp, body=None)


def model_gone():
    resp = httpx.Response(404, request=httpx.Request("POST", "https://api.groq.com/x"))
    return openai.NotFoundError("model not found", response=resp, body=None)


def msg(content=None, tool_calls=None, tokens=(100, 20)):
    """A chat completion whose message has `content` (str or dict -> json) and/or tool calls."""
    if isinstance(content, (dict, list)):
        content = json.dumps(content)
    calls = None
    if tool_calls:
        calls = [
            SimpleNamespace(id=f"call_{i}", type="function",
                            function=SimpleNamespace(name=name, arguments=json.dumps(args)))
            for i, (name, args) in enumerate(tool_calls)
        ]
    message = SimpleNamespace(role="assistant", content=content, tool_calls=calls)
    usage = SimpleNamespace(prompt_tokens=tokens[0], completion_tokens=tokens[1],
                            total_tokens=sum(tokens))
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


class FakeGroq:
    """script: list of responses/exceptions, or a callable(kwargs) -> response/exception."""

    def __init__(self, script):
        self.script = script
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.script(kwargs) if callable(self.script) else self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


async def no_sleep(_):
    return None
