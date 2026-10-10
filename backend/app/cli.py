"""CLI: python -m app.cli <repo_url>  -> prints the deterministic audit report as JSON."""
import argparse
import asyncio
import json
import logging
import sys

from app.audit import run_deterministic_audit
from app.tracing import flush, init_tracing


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.cli", description="PreJudge deterministic audit")
    p.add_argument("repo_url", help="public GitHub repo URL or owner/name")
    p.add_argument("--no-trace", action="store_true", help="don't send traces to neatlogs")
    args = p.parse_args(argv)

    # Logs go to stderr so stdout stays pure JSON.
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    if not args.no_trace:
        init_tracing()
    try:
        report = asyncio.run(run_deterministic_audit(args.repo_url))
    finally:
        flush()
    json.dump(report, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
