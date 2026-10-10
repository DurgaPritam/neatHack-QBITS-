"""Strict schemas for every JSON the LLM returns."""
import json
import re
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, field_validator

Category = Literal["agent", "tools", "demo_video", "building_in_public", "usefulness"]
MAX_CLAIMS = 8

_PROFANITY = re.compile(
    r"\b(fuck\w*|shit\w*|bitch\w*|bastard\w*|asshole\w*|dick(head)?s?|cunt\w*|crap|damn\w*|wtf)\b", re.I)


def _clip(n: int):
    """Truncate over-long free text instead of rejecting the whole answer."""
    def f(v):
        return v[:n] if isinstance(v, str) else v
    return BeforeValidator(f)


Short = Annotated[str, _clip(300)]
Medium = Annotated[str, _clip(500)]


def _category(v):
    """Map the model's free-form category onto the rubric instead of rejecting the answer."""
    if not isinstance(v, str):
        return "usefulness"
    low = v.lower().replace(" ", "_").replace("-", "_")
    for cat, words in (("tools", ("tool", "neatlogs", "entire", "cfo", "trac", "integrat", "mcp")),
                       ("demo_video", ("video", "demo")),
                       ("building_in_public", ("public", "commit", "post", "social")),
                       ("agent", ("agent", "llm", "model", "recover", "retry", "eval", "bench"))):
        if low == cat or any(w in low for w in words):
            return cat
    return "usefulness"


class Claim(BaseModel):
    id: Annotated[str, BeforeValidator(lambda v: str(v)[:10])]
    text: Short = Field(min_length=3)
    quote: Short = ""
    category: Annotated[Category, BeforeValidator(_category)] = "agent"
    # literal strings likely to appear in code/config if the claim is true (for pre-search)
    search: Annotated[list[Short], BeforeValidator(lambda v: [v] if isinstance(v, str) else (v or [])[:4])] = []


class ClaimList(BaseModel):
    claims: list[Claim]  # required: a missing key must trigger a repair, not silently mean "none"
    injection_attempts: list[Short] = Field(default_factory=list)

    @field_validator("claims")
    @classmethod
    def cap(cls, v: list[Claim]) -> list[Claim]:
        seen, out = set(), []
        for c in v:
            if c.id not in seen:
                seen.add(c.id)
                out.append(c)
        return out[:MAX_CLAIMS]


class Evidence(BaseModel):
    ref: Medium
    note: Short = ""


class ClaimResult(BaseModel):
    claim_id: Annotated[str, BeforeValidator(str)]
    status: Literal["verified", "unverified", "contradicted"]
    evidence: list[Evidence] = Field(default_factory=list)
    reason: Medium = ""


class Estimate(BaseModel):
    score: float = Field(ge=0, le=10)
    evidence: list[Medium] = Field(default_factory=list)
    reason: Medium = ""


class VerifyResult(BaseModel):
    results: list[ClaimResult]
    estimates: dict[Literal["agent_quality", "usefulness"], Estimate] = Field(default_factory=dict)
    injection_attempts: list[Short] = Field(default_factory=list)


class FixItem(BaseModel):
    check_id: str
    fix: str = Field(min_length=5, max_length=400)


class Verdict(BaseModel):
    roast: str = Field(min_length=10, max_length=450)
    fixes: list[FixItem] = Field(default_factory=list)
    best_thing: str = Field(min_length=5, max_length=300)

    @field_validator("roast")
    @classmethod
    def short_and_clean(cls, v: str) -> str:
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", v.strip()) if s]
        if len(sentences) > 3:
            raise ValueError(f"roast must be 1-3 sentences, got {len(sentences)}")
        return v.strip()

    @field_validator("roast", "best_thing")
    @classmethod
    def no_profanity(cls, v: str) -> str:
        if _PROFANITY.search(v):
            raise ValueError("no profanity allowed")
        return v


def parse_json(text: str | None, model: type[BaseModel]) -> BaseModel:
    """Parse model output (tolerating ```json fences) and validate. Raises ValueError."""
    if not text:
        raise ValueError("empty response")
    t = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    if fence:
        t = fence.group(1)
    try:
        data = json.loads(t)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    return model.model_validate(data)
