"""CLI: python -m app.cli <repo_url> [--full] -> prints the audit report as JSON.

Default: deterministic checks only (M1). --full: deterministic + LLM agent + score + verdict.
"""
import argparse
import asyncio
import json
import logging
import sys

from app.audit import run_deterministic_audit, run_full_audit
from app.tracing import flush, init_tracing


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.cli", description="PreJudge deterministic audit")
    p.add_argument("repo_url", help="public GitHub repo URL or owner/name")
    p.add_argument("--full", action="store_true", help="run the LLM agent, scoring and verdict too")
    p.add_argument("--test", action="store_true", help='tag the run as "test" in neatlogs (default "real")')
    p.add_argument("--no-trace", action="store_true", help="don't send traces to neatlogs")
    args = p.parse_args(argv)

    # Logs go to stderr so stdout stays pure JSON.
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    if not args.no_trace:
        init_tracing()
    try:
        if args.full:
            run_kind = "test" if args.test else "real"
            report = asyncio.run(run_full_audit(args.repo_url, run_kind=run_kind))
        else:
            report = asyncio.run(run_deterministic_audit(args.repo_url))
    finally:
        flush()
    json.dump(report, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
