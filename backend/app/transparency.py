"""/transparency: live, aggregate numbers about PreJudge itself, vs the cfo.ai plan's assumption.

Aggregates only: no repo names, no per-audit rows. Real, visible audits (no tests, examples or
removed ones). Costs are at Groq list price (costs.py), the plan's basis. Cached for 5 minutes.
"""
import time

from app import costs, db

PLAN_COST_PER_AUDIT = 0.0095            # cfo.ai v3: $0.005 quick, $0.02 deep, 70% quick-only, blended
PLAN_QUICK, PLAN_DEEP = 0.005, 0.02
CFO_PLAN_URL = "https://cfo.ai/s/xBCsLLiMtconXUBf"
ENTIRE_URL = "https://entire.io/gh/DurgaPritam/neatHack-QBITS-"
CACHE_S = 300
_cache: dict = {"at": 0.0, "body": None}


def _avg(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 6) if xs else None


def compute() -> dict:
    rows = db.transparency_rows()
    worked = [r for r in rows if not r["cached_from"]]          # reused results cost nothing
    quick_tok, quick_cost, quick_ms, deep_tok, deep_cost, deep_ms = [], [], [], [], [], []
    with_fallback, llm_audits, total_cost = 0, 0, 0.0
    for r in worked:
        res = r["result"] or {}
        u, t = res.get("usage") or {}, res.get("timing_ms") or {}
        if (u.get("quick") or {}).get("calls"):
            quick_tok.append(u["quick"]["total_tokens"]); quick_cost.append(costs.usage_cost(u["quick"]))
            if t.get("quick"): quick_ms.append(t["quick"])
        if (u.get("deep") or {}).get("calls"):
            deep_tok.append(u["deep"]["total_tokens"]); deep_cost.append(costs.usage_cost(u["deep"]))
            if t.get("deep"): deep_ms.append(t["deep"])
        if u.get("calls"):
            llm_audits += 1
            total_cost += costs.usage_cost(u.get("quick")) + costs.usage_cost(u.get("deep"))
            if any(str(s.get("name", "")).endswith(".fallback") for s in r["steps"] or []):
                with_fallback += 1
    blended = round(total_cost / llm_audits, 6) if llm_audits else None
    saved = db.metrics()["totals"].get("tokens_saved", 0)
    deep_share = round(len(deep_cost) / llm_audits, 3) if llm_audits else None
    if blended is None:
        verdict = "No audits with LLM calls yet."
    else:
        ratio = blended / PLAN_COST_PER_AUDIT
        verdict = (f"Actual ${blended:.4f} per audit vs plan ${PLAN_COST_PER_AUDIT:.4f}: "
                   + (f"{(1 - ratio) * 100:.0f}% under plan" if ratio < 1 else f"{(ratio - 1) * 100:.0f}% over plan")
                   + (f" ({deep_share * 100:.0f}% of audits ran a deep check; the plan assumes 30%)" if deep_share is not None else ""))
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "audits": len(rows), "audits_that_ran": len(worked), "reused_results": len(rows) - len(worked),
        "unique_repos": len({r["repo_key"] for r in rows if r["repo_key"]}),
        "quick": {"audits": len(quick_tok), "avg_tokens": _avg(quick_tok), "avg_cost_usd": _avg(quick_cost),
                  "avg_seconds": round(_avg(quick_ms) / 1000, 1) if quick_ms else None},
        "deep": {"audits": len(deep_tok), "avg_tokens": _avg(deep_tok), "avg_cost_usd": _avg(deep_cost),
                 "avg_seconds": round(_avg(deep_ms) / 1000, 1) if deep_ms else None},
        "fallback_rate": round(with_fallback / llm_audits, 3) if llm_audits else None,
        "tokens_saved_by_reuse": saved,
        "plan": {"cost_per_audit_usd": PLAN_COST_PER_AUDIT, "quick_usd": PLAN_QUICK, "deep_usd": PLAN_DEEP,
                 "deep_share": 0.3, "url": CFO_PLAN_URL},
        "actual": {"cost_per_audit_usd": blended, "deep_share": deep_share},
        "plan_vs_actual": verdict,
        "pricing": "Groq list price per million tokens; we run on the free tier, so this is what the same tokens would cost",
        "links": {"cfo_ai": CFO_PLAN_URL, "entire": ENTIRE_URL, "neatlogs": "https://neatlogs.com"},
    }


def get(now: float | None = None) -> dict:
    now = time.monotonic() if now is None else now
    if _cache["body"] is None or now - _cache["at"] >= CACHE_S:
        _cache.update(at=now, body=compute())
    return _cache["body"]


def reset() -> None:
    _cache.update(at=0.0, body=None)
