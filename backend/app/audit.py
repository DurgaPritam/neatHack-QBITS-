"""Deterministic audit pass (M1): gather repo evidence, run rubric checks, return a report.

Every external call is a recorded step. Failures never abort the audit; they are
logged and, where possible, a fallback is tried so a partial report still comes back.
"""
import asyncio
from datetime import datetime, timezone

from app.steps import StepLog
from app.tools import rubric
from app.tools.github import GitHubClient, GitHubError, parse_repo_url
from app.tools.links import check_links, extract_links
from app.tools.video import get_duration
from app.tracing import span

README_FALLBACK_NAMES = ("README.md", "readme.md", "README.rst", "README")


def _failed(log: StepLog) -> bool:
    return log.steps[-1].status == "failed"


@span("WORKFLOW", "prejudge.deterministic_audit")
async def run_deterministic_audit(repo_url: str, token: str | None = None,
                                  transport=None, log: StepLog | None = None,
                                  ctx: dict | None = None) -> dict:
    """ctx, if given, is filled with the raw material the agent needs (README, tree, commits)."""
    log = log or StepLog()
    ctx = {} if ctx is None else ctx
    report: dict = {
        "repo_url": repo_url,
        "audited_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "deterministic",
        "window": {"start": rubric.WINDOW_START.isoformat(), "end": rubric.WINDOW_END.isoformat()},
    }

    with log.step("parse_url") as s:
        ref = parse_repo_url(repo_url)
        s.detail = ref.full_name
    if _failed(log):
        check = rubric.check_repo_public(None, "invalid_url")
        check["detail"] = log.steps[-1].detail
        return {**report, "steps": log.to_list(), "checks": [check],
                "summary": rubric.summarize([check]), "partial": True}

    repo = readme = commits = None
    repo_error = None
    tree_paths: list[str] = []
    dep_files: dict[str, str] = {}
    commits_truncated = False
    links: list[dict] = []
    videos_meta: list[dict] = []

    async with GitHubClient(token=token, transport=transport) as gh:
        report["github_authenticated"] = gh.authenticated

        with log.step("github.get_repo") as s:
            repo = await gh.get_repo(ref)
            s.detail = f"default branch {repo['default_branch']}"
        if _failed(log):
            repo_error = log.steps[-1].error_kind
        branch = repo["default_branch"] if repo else "HEAD"

        # Nothing more to read from a repo that's missing or private.
        if repo_error in ("not_found", "private", "invalid_url"):
            for name in ("github.get_readme", "github.get_tree", "github.get_commits", "links.check"):
                log.skip(name, f"repo unavailable ({repo_error})")
        else:
            api_ok = repo_error is None

            if api_ok:
                with log.step("github.get_readme") as s:
                    r = await gh.get_readme(ref)
                    readme = r["text"]
                    ctx["readme_path"] = r["path"]
                    s.detail = f"{r['path']} ({len(readme)} chars)"
            if readme is None:
                # Fallback: raw.githubusercontent.com doesn't count against the API rate limit.
                with log.step("github.get_readme_raw_fallback") as s:
                    for name in README_FALLBACK_NAMES:
                        try:
                            readme = await gh.get_file(ref, name, branch)
                            ctx["readme_path"] = name
                            s.detail = f"got {name} via raw"
                            break
                        except GitHubError as exc:
                            if exc.kind != "not_found":
                                raise
                    else:
                        s.status = "failed"
                        s.error_kind = "not_found"
                        s.detail = "no README at repo root"

            if api_ok:
                with log.step("github.get_tree") as s:
                    tree = await gh.get_tree(ref, branch)
                    tree_paths = [f["path"] for f in tree["files"]]
                    s.detail = f"{len(tree_paths)} files{' (truncated)' if tree['truncated'] else ''}"
                    report["head_sha"] = tree["sha"]
            else:
                log.skip("github.get_tree", f"API unavailable ({repo_error})")

            to_fetch = rubric.pick_dependency_files(tree_paths)
            if to_fetch:
                with log.step("github.get_dependency_files") as s:
                    missed = []
                    for path in to_fetch:
                        try:
                            dep_files[path] = await gh.get_file(ref, path, branch)
                        except GitHubError as exc:
                            missed.append(f"{path}: {exc.kind}")
                    s.detail = f"fetched {len(dep_files)}/{len(to_fetch)}"
                    if missed:
                        s.data["missed"] = missed

            if api_ok:
                with log.step("github.get_commits") as s:
                    c = await gh.get_commits(ref, branch)
                    commits, commits_truncated = c["commits"], c["truncated"]
                    s.detail = f"{c['count']} commits{' (truncated)' if commits_truncated else ''}"
            else:
                log.skip("github.get_commits", f"API unavailable ({repo_error})")

            if readme:
                with log.step("links.check") as s:
                    urls = extract_links(readme)
                    links = await check_links(urls)
                    dead = sum(1 for l in links if l["ok"] is False)
                    s.detail = f"{len(links)} links, {dead} dead"
                video_links = [l["url"] for l in links if l["kind"] == "video" and l["ok"] is not False][:2]
                if video_links:
                    with log.step("video.duration") as s:
                        videos_meta = list(await asyncio.gather(*(get_duration(u) for u in video_links)))
                        s.detail = "; ".join(f"{m['duration'] or 'unknown'}"
                                             + (f" ({m['reason']})" if m["reason"] else "") for m in videos_meta)
                        if all(m["status"] == "unknown" for m in videos_meta):
                            s.status, s.error_kind = "failed", "duration_unknown"
            else:
                log.skip("links.check", "no README text")

        report["github_rate_limit_remaining"] = gh.rate_limit_remaining

    readme_text = readme or ""
    ctx.update(ref=ref, branch=branch, readme=readme_text, tree_paths=tree_paths,
               commits=commits or [], repo_available=repo_error not in ("not_found", "private"))
    checks = [
        rubric.check_repo_public(repo, repo_error),
        rubric.check_prompt_injection({"README": readme_text, **dep_files}),
    ]
    if repo_error not in ("not_found", "private"):
        checks += [
            rubric.check_readme(readme),
            rubric.check_commit_window(commits, commits_truncated),
            rubric.check_neatlogs_usage(dep_files, readme_text),
            rubric.check_neatlogs_traces(links),
            rubric.check_entire(tree_paths, readme_text, links),
            rubric.check_cfo_ai(readme_text, links),
            rubric.check_demo_video(links, videos_meta),
            rubric.check_public_posts(readme_text, links),
            rubric.check_before_after(readme_text),
            rubric.check_failure_run(readme_text),
            rubric.check_dead_links(links),
        ]

    report.update({
        "repo": repo,
        "partial": any(s.status != "ok" for s in log.steps),
        "steps": log.to_list(),
        "checks": checks,
        "summary": rubric.summarize(checks),
        "links": links,
        "videos": videos_meta,
        "files_seen": len(tree_paths),
        "dependency_files": list(dep_files),
    })
    return report


async def run_full_audit(repo_url: str, *, audit_id: str | None = None, run_kind: str = "real",
                         log: StepLog | None = None, llm=None, transport=None,
                         token: str | None = None) -> dict:
    """Deterministic pass + LLM agent + scoring + verdict. Always returns a report."""
    import time
    import uuid

    from app.agent.loop import run_agent, template_verdict
    from app.scoring import compute_score
    from app.tracing import audit_context

    audit_id = audit_id or uuid.uuid4().hex[:12]
    log = log or StepLog()
    t0 = time.monotonic()
    with audit_context(audit_id, run_kind, repo_url):
        ctx: dict = {}
        report = await run_deterministic_audit(repo_url, token=token, transport=transport, log=log, ctx=ctx)
        t_det = int((time.monotonic() - t0) * 1000)
        if ctx.get("repo_available"):
            async with GitHubClient(token=token, transport=transport) as gh:
                agent = await run_agent(report, ctx, log, llm=llm, gh=gh)
        else:
            # Nothing for an LLM to read: score + template verdict straight from the checks.
            log.skip("agent", "repo unavailable; skipping LLM phases")
            score = compute_score(report["checks"])
            agent = {"claims": [], "estimates": {}, "injection": {"detected": False},
                     "score": score, "verdict": {**template_verdict(score, report), "source": "template"},
                     "tool_calls": 0, "files_read": [], "usage": None, "agent_ms": 0}

    usage = agent.pop("usage")
    report.update(
        audit_id=audit_id,
        run_kind=run_kind,
        mode="full",
        score=agent.pop("score"),
        verdict=agent.pop("verdict"),
        agent=agent,
        usage=usage or {"total_tokens": 0, "calls": 0},
        timing_ms={"deterministic": t_det, "agent": agent.pop("agent_ms"),
                   "total": int((time.monotonic() - t0) * 1000)},
        steps=log.to_list(),
        partial=any(s.status == "failed" for s in log.steps),
    )
    return report
