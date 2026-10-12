"""LLM cost at list price, and the 'glass box': how a verdict was made, step by step.

We run on Groq's free tier, so every dollar figure is what the same tokens would cost at Groq's
list price, the basis of the cfo.ai plan ($0.80 / $4.00 per million input / output tokens on the
primary model). MODEL_PRICES overrides it: "model=in:out,model=in:out" in $ per million tokens.
"""
from app import config
from app.public import friendly_step

DEFAULT_PRICES = "qwen/qwen3.8-27b=0.80:4.00,openai/gpt-oss-120b=0.15:0.75,openai/gpt-oss-20b=0.10:0.50"
INPUT_SHARE = 0.85   # per-step logs keep total tokens only; our calls are ~85% prompt (see usage totals)


def prices() -> dict[str, tuple[float, float]]:
    out = {}
    for part in (config.env("MODEL_PRICES") or DEFAULT_PRICES).split(","):
        try:
            model, rate = part.strip().split("=")
            i, o = rate.split(":")
            out[model.strip()] = (float(i), float(o))
        except ValueError:
            continue
    return out


def _rate(model: str | None, p: dict) -> tuple[float, float]:
    return p.get(model or "", max(p.values(), key=sum) if p else (0.0, 0.0))  # unknown model: the dearest


def usage_cost(usage_phase: dict | None) -> float:
    """Exact split: prompt and completion tokens per model."""
    p, total = prices(), 0.0
    for model, u in ((usage_phase or {}).get("by_model") or {}).items():
        i, o = _rate(model, p)
        total += (u.get("prompt_tokens", 0) * i + u.get("completion_tokens", 0) * o) / 1e6
    return total


def step_cost(model: str | None, tokens: int) -> float:
    i, o = _rate(model, prices())
    return tokens * (INPUT_SHARE * i + (1 - INPUT_SHARE) * o) / 1e6


def _kind(step: dict) -> str | None:
    name, data = step.get("name", ""), step.get("data") or {}
    if name.endswith(".fallback"):
        return "fallback"
    if name.endswith(".wait_for_quota"):
        return "wait"
    if name.endswith(("_retry", ".repair")) or "retry_in_s" in data:
        return "retry"
    if step.get("status") == "failed":
        return "failed"
    return None


def glass_box(steps: list[dict], usage: dict | None, timing_ms: dict | None) -> dict:
    """Only whitelisted fields leave the server: no prompts, repo text, keys, IPs or raw errors."""
    rows, retries, fallbacks, waits = [], 0, 0, 0
    for s in steps or []:
        s = friendly_step(s)                       # raw errors -> friendly text
        data = s.get("data") or {}
        tokens = int(data.get("tokens") or 0)
        model = data.get("model") if isinstance(data.get("model"), str) else None
        kind = _kind(s)
        retries += kind == "retry" or (kind == "failed" and s.get("error_kind") == "rate_limited")
        fallbacks += kind == "fallback"
        waits += kind == "wait"
        rows.append({
            "name": s.get("name", ""), "status": s.get("status"), "ms": int(s.get("duration_ms") or 0),
            "tokens": tokens, "model": model if s.get("name", "").startswith("llm") else None,
            "cost_usd": round(step_cost(model, tokens), 6) if tokens else 0.0, "kind": kind,
            "wait_s": data.get("wait_s"), "to_model": data.get("model") if kind == "fallback" else None,
            "note": s.get("detail") if s.get("status") == "failed" or kind == "fallback" else None,
        })
    u = usage or {}
    phases = {ph: {"tokens": (u.get(ph) or {}).get("total_tokens", 0), "calls": (u.get(ph) or {}).get("calls", 0),
                   "failed_calls": (u.get(ph) or {}).get("failed_calls", 0),
                   "cost_usd": round(usage_cost(u.get(ph)), 6), "ms": (timing_ms or {}).get(ph)}
              for ph in ("quick", "deep") if u.get(ph)}
    return {"steps": rows, "phases": phases,
            "totals": {"tokens": u.get("total_tokens", sum(r["tokens"] for r in rows)),
                       "cost_usd": round(sum(p["cost_usd"] for p in phases.values()), 6),
                       "ms": (timing_ms or {}).get("total") or sum(r["ms"] for r in rows),
                       "retries": retries, "fallbacks": fallbacks, "quota_waits": waits},
            "pricing": "Groq list price per million tokens (we run on the free tier, so this is what it would cost)",
            "traced_with": "neatlogs"}
