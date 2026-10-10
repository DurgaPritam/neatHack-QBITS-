"""Measure quick-audit throughput and project quick/deep audits per hour.

    python -m scripts.throughput [--n 10] [--deep-report path.json ...]

Runs N quick audits back to back through the shared QuotaPool (tagged "test"), like the
quick worker does, and reports the measured rate. Then projects sustainable rates from
the per-model Groq limits (headers give TPM and RPD; TPD from the Groq docs, GROQ_TPD).
Deep-phase cost per audit comes from --deep-report files (CLI --full output).
"""
import argparse
import asyncio
import json
import statistics
import sys
import time

from app.audit import run_quick_audit
from app.llm import POOL, configured_models
from app.tracing import flush, init_tracing

REPOS = [
    "openai/swarm", "huggingface/smolagents", "langchain-ai/open_deep_research", "pallets/itsdangerous",
    "tiangolo/typer", "encode/httpx", "psf/requests", "pallets/click", "Textualize/rich",
    "fastapi/full-stack-fastapi-template", "simonw/llm", "karpathy/nanoGPT",
]
RPM_PER_MODEL = 30  # Groq docs; not exposed in headers


async def burst(n: int) -> dict:
    rows = []
    t0 = time.monotonic()
    for repo in REPOS[:n]:
        r = await run_quick_audit(f"https://github.com/{repo}", run_kind="test")
        steps = r["steps"]
        rows.append({
            "repo": repo, "ms": r["phases"]["quick"]["ms"],
            "tokens": r["phases"]["quick"]["usage"]["total_tokens"],
            "calls": r["phases"]["quick"]["usage"]["calls"],
            "waits_s": round(sum(s["data"].get("wait_s", 0) for s in steps if "wait_for_quota" in s["name"]), 1),
            "rate_limited": sum(1 for s in steps if s.get("error_kind") == "rate_limited"),
            "verdict": r["verdict"]["source"],
            "roast_rejected": [s["detail"][:120] for s in steps if "roast_rejected" in s["name"]],
        })
        print(json.dumps(rows[-1]), file=sys.stderr)
    elapsed = time.monotonic() - t0
    return {"rows": rows, "elapsed_s": round(elapsed, 1), "per_hour": round(n / elapsed * 3600)}


def project(tokens: float, calls: float, seconds: float, models: int, limits: dict) -> dict:
    """Audits/hour each limit allows; the smallest wins."""
    tpm = sum(limits["tpm"]) if limits["tpm"] else 8000 * models
    rpd = sum(limits["rpd"]) if limits["rpd"] else 1000 * models
    tpd = limits["tpd"] * models
    bounds = {
        "latency (one at a time)": 3600 / seconds,
        "tokens/min (all models)": tpm * 60 / tokens,
        "requests/min": RPM_PER_MODEL * models * 60 / calls,
        "requests/day, spread over 24h": rpd / calls / 24,
        "tokens/day, spread over 24h": tpd / tokens / 24,
    }
    burst_bounds = {k: v for k, v in bounds.items() if "24h" not in k}
    return {
        "bounds_per_hour": {k: round(v, 1) for k, v in bounds.items()},
        "burst_per_hour": round(min(burst_bounds.values()), 1),
        "sustained_per_hour_24h": round(min(bounds.values()), 1),
        "per_day": round(min(bounds["tokens/day, spread over 24h"], bounds["requests/day, spread over 24h"]) * 24),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=10)
    p.add_argument("--deep-report", nargs="*", default=[])
    args = p.parse_args()
    init_tracing()
    try:
        b = asyncio.run(burst(args.n))
    finally:
        flush()
    snap = POOL.snapshot()
    models = configured_models()
    limits = {"tpm": [q["tpm_limit"] for q in snap.values()],
              "rpd": [q["rpd_remaining"] for q in snap.values() if q["rpd_remaining"] is not None],
              "tpd": next(iter(snap.values()))["tpd_limit"] if snap else 200_000}
    limits["rpd"] = [1000] * len(models)  # daily allowance (headers show what's *left* today)
    q_tok = statistics.mean(r["tokens"] for r in b["rows"])
    q_calls = statistics.mean(r["calls"] for r in b["rows"])
    q_s = statistics.mean(r["ms"] for r in b["rows"]) / 1000
    out = {
        "models": models,
        "quick_measured": {**b, "avg_tokens": round(q_tok), "avg_calls": round(q_calls, 2),
                           "avg_s": round(q_s, 1), "pool_after": snap},
        "quick_projection": project(q_tok, q_calls, q_s, len(models), limits),
    }
    deep = [json.load(open(f)) for f in args.deep_report]
    if deep:
        d_tok = statistics.mean(r["phases"]["deep"]["usage"]["total_tokens"] for r in deep)
        d_calls = statistics.mean(r["phases"]["deep"]["usage"]["calls"] for r in deep)
        d_s = statistics.mean(r["phases"]["deep"]["ms"] for r in deep) / 1000
        out["deep_measured"] = {"audits": len(deep), "avg_tokens": round(d_tok), "avg_calls": round(d_calls, 2),
                                "avg_s": round(d_s, 1)}
        out["deep_projection"] = project(d_tok, d_calls, d_s, len(models), limits)
        # a full audit spends quick + deep tokens from the same daily budget
        out["full_audits_per_day"] = round(limits["tpd"] * len(models) / (q_tok + d_tok))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
