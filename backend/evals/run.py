"""Eval runner: audit every repo in evals/repos.yaml and score PreJudge against the labels.

    python -m evals.run                    # quick for all, deep as budget allows, then report
    python -m evals.run --no-deep          # quick phase only
    python -m evals.run --only repo-a own  # a subset
    python -m evals.run --sheets           # also write label sheets for repos that have none
    python -m evals.run --report-only      # re-score the latest run against (new) labels, no audits

Runs use the admin reserve and are tagged run_kind "test" in neatlogs (audit id = session id).
Raw reports go to evals/private/runs/<date>/ (gitignored: other teams' repos). The committed
summary, evals/results/<date>.json, only has anonymised ids, verdicts and label outcomes.
"""
import argparse
import asyncio
import json
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

from evals.labels import EVAL_CHECKS, parse_sheet, truth_for, write_sheet

HERE = Path(__file__).resolve().parent
RUNS = HERE / "private" / "runs"
DEEP_EST_TOKENS = 18_000


def load_repos(only: list[str] | None = None) -> list[dict]:
    entries = yaml.safe_load((HERE / "repos.yaml").read_text())["repos"]
    private = HERE / "private" / "repos.yaml"
    urls = yaml.safe_load(private.read_text()) if private.exists() else {}
    out = []
    for e in entries:
        url = e.get("url") or (urls or {}).get(e["id"])
        if not url:
            print(f"skip {e['id']}: no URL (add it to evals/private/repos.yaml)", file=sys.stderr)
            continue
        if only and e["id"] not in only:
            continue
        out.append({**e, "url": url})
    return out


async def audit_one(entry: dict, deep: bool, pool_ok) -> dict:
    from app.audit import run_deep_audit, run_quick_audit
    from app.llm import LLM
    from app.steps import StepLog

    audit_id = uuid.uuid4().hex[:12]
    log, ctx = StepLog(), {}
    t0 = time.monotonic()
    report = await run_quick_audit(entry["url"], audit_id=audit_id, run_kind="test", log=log, ctx=ctx,
                                   use_reserve=True)
    phase = "quick"
    if deep and ctx.get("repo_available"):
        if pool_ok():
            llm = LLM(log, priority="low", use_reserve=True)
            report = await run_deep_audit(report, ctx, log=log, llm=llm, use_reserve=True)
            phase = "deep"
        else:
            log.skip("deep", "eval: not enough LLM budget left today")
    return {"id": entry["id"], "audit_id": audit_id, "phase": phase, "report": report,
            "seconds": round(time.monotonic() - t0, 1),
            "tokens": (report.get("usage") or {}).get("total_tokens", 0)}


def score_run(runs: list[dict]) -> dict:
    """Compare each run's verdicts with the label sheets."""
    per_check: dict[str, Counter] = {cid: Counter() for cid in EVAL_CHECKS}
    errors: Counter = Counter()
    claims = Counter()
    repos = []
    for r in runs:
        sheet = HERE / "labels" / f"{r['id']}.md"
        labels = parse_sheet(sheet.read_text()) if sheet.exists() else {"checks": {}, "claims": {}}
        checks = {c["id"]: c for c in r["report"].get("checks", [])}
        row = {"id": r["id"], "phase": r["phase"], "audit_id": r["audit_id"],
               "score": (r["report"].get("score") or {}).get("score"), "tokens": r["tokens"],
               "seconds": r["seconds"], "checks": {}}
        for cid in EVAL_CHECKS:
            c = checks.get(cid)
            if not c:
                continue
            got = c["status"]
            lab = labels["checks"].get(cid)
            outcome = "unlabelled"
            if lab and lab["label"]:
                truth = truth_for(lab)
                if lab["label"] == "ok" and got == lab["verdict"]:
                    outcome = "correct"
                elif truth is None:
                    outcome = "unknown" if got == lab["verdict"] else "changed"
                elif got == truth:
                    outcome = "correct"
                else:
                    outcome = "false_fail" if got == "fail" and truth in ("pass", "warn") else \
                        "false_pass" if got == "pass" and truth in ("fail", "warn") else "wrong"
                per_check[cid][outcome] += 1
                if outcome not in ("correct", "unknown"):
                    errors[(cid, outcome)] += 1
            row["checks"][cid] = {"verdict": got, "outcome": outcome}
        for cl in (r["report"].get("agent") or {}).get("claims", []):
            # claims are re-extracted every run: match the labelled one by its README quote
            lab = next((v for v in labels["claims"].values() if v["label"] and v["quote"]
                        and v["quote"][:60] == (cl.get("quote") or cl["claim"])[:60]), None)
            if not lab:
                claims["unlabelled"] += 1
                continue
            truth = truth_for(lab)
            claims["agree" if truth and cl["status"] == truth else "disagree" if truth else "unknown"] += 1
        repos.append(row)

    def acc(c: Counter) -> float | None:
        n = sum(v for k, v in c.items() if k not in ("unknown",))
        return round(100 * c["correct"] / n, 1) if n else None

    total = sum(per_check.values(), Counter())
    labelled_claims = claims["agree"] + claims["disagree"]
    return {
        "repos": repos,
        "per_check": {cid: {"accuracy": acc(c), **dict(c)} for cid, c in per_check.items()},
        "overall": {"accuracy": acc(total), "false_fails": total["false_fail"], "false_passes": total["false_pass"],
                    "other_wrong": total["wrong"] + total["changed"], "labelled": sum(total.values())},
        "claims": {"agreement": round(100 * claims["agree"] / labelled_claims, 1) if labelled_claims else None,
                   **dict(claims)},
        "top_errors": [{"check": c, "kind": k, "count": n} for (c, k), n in errors.most_common(5)],
    }


def print_summary(summary: dict) -> None:
    o = summary["overall"]
    print(f"\nOverall accuracy: {o['accuracy']}% over {o['labelled']} labelled checks · "
          f"false fails {o['false_fails']} · false passes {o['false_passes']} · other wrong {o['other_wrong']}")
    print(f"Claim agreement: {summary['claims']['agreement']}% ({summary['claims']})")
    print("\nPer check:")
    for cid, s in summary["per_check"].items():
        print(f"  {cid:20} {s}")
    print("\nTop errors:")
    for e in summary["top_errors"]:
        print(f"  {e['count']}× {e['kind']} on {e['check']}")
    print("\nRepos:")
    for r in summary["repos"]:
        verdicts = " ".join(f"{k.split('_')[0]}={v['verdict']}" for k, v in r["checks"].items())
        print(f"  {r['id']:20} {r['phase']:5} score {r['score']} · {r['tokens']} tok · {r['seconds']}s · {verdicts}")


def save(runs: list[dict], date: str, label: str) -> Path:
    raw = RUNS / f"{date}-{label}"
    raw.mkdir(parents=True, exist_ok=True)
    for r in runs:
        (raw / f"{r['id']}.json").write_text(json.dumps(r, indent=1, default=str))
    return raw


def latest_runs() -> list[dict]:
    dirs = sorted(p for p in RUNS.glob("*") if p.is_dir()) if RUNS.exists() else []
    if not dirs:
        raise SystemExit("no saved runs yet; run without --report-only first")
    return [json.loads(p.read_text()) for p in sorted(dirs[-1].glob("*.json"))]


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="python -m evals.run")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--no-deep", action="store_true")
    ap.add_argument("--sheets", action="store_true", help="write label sheets for repos without one")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--tag", default="run", help="name for this run, e.g. baseline or after-fix-1")
    args = ap.parse_args(argv)

    from app import budget, db, tracing
    from app.llm import POOL, configured_models, judge_models

    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if args.report_only:
        runs = latest_runs()
    else:
        tracing.init_tracing("prejudge-evals")
        db.connect(HERE / "private" / "evals.db")   # eval audits never touch the app database
        budget.attach(POOL)
        models = judge_models() or configured_models()
        pool_ok = lambda: any(POOL.daily_ok(m, DEEP_EST_TOKENS, use_reserve=True) for m in models)  # noqa: E731
        runs = []
        for entry in load_repos(args.only):
            print(f"auditing {entry['id']}…", file=sys.stderr)
            try:
                r = asyncio.run(audit_one(entry, not args.no_deep, pool_ok))
            except Exception as exc:  # one broken repo never stops the eval
                print(f"  {entry['id']} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
                continue
            runs.append(r)
            print(f"  {r['phase']} · score {(r['report'].get('score') or {}).get('score')} · {r['tokens']} tok · "
                  f"audit {r['audit_id']}", file=sys.stderr)
            if args.sheets and not (HERE / "labels" / f"{entry['id']}.md").exists():
                write_sheet(HERE / "labels" / f"{entry['id']}.md", entry, entry["url"], r["report"],
                            {"audit_id": r["audit_id"], "phase": r["phase"], "date": date})
        tracing.flush()
        save(runs, date, args.tag)

    summary = score_run(runs)
    summary.update(date=date, tag=args.tag, repos_run=len(runs))
    out = HERE / "results" / f"{date}-{args.tag}.json"
    out.write_text(json.dumps(summary, indent=1))
    print_summary(summary)
    print(f"\nsaved {out.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main(sys.argv[1:])
