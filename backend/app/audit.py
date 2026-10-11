"""Deterministic audit pass (M1): gather repo evidence, run rubric checks, return a report.

Every external call is a recorded step. Failures never abort the audit; they are
logged and, where possible, a fallback is tried so a partial report still comes back.
"""
import asyncio
from datetime import datetime, timezone

from app import config, replay
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
        "checks_version": rubric.CHECKS_VERSION,
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
    entire_refs: dict | None = None

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

            if api_ok:
                with log.step("github.get_entire_refs") as s:
                    entire_refs = await gh.get_entire_refs(ref)
                    s.detail = (f"{len(entire_refs['ids'])} checkpoint refs"
                                + (f", branch {entire_refs['branch']}" if entire_refs["branch"] else ""))
            else:
                log.skip("github.get_entire_refs", f"API unavailable ({repo_error})")

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
                        s.detail = "; ".join(m["duration"] or m["reason"] or "unknown" for m in videos_meta)
                        s.data["sources"] = [m.get("source") or m.get("reason_code") for m in videos_meta]
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
            rubric.check_neatlogs_traces(links, readme_text, tree_paths),
            rubric.check_entire(tree_paths, readme_text, links, commits, entire_refs,
                               (repo or {}).get("full_name") or ref.full_name),
            rubric.check_cfo_ai(readme_text, links),
            rubric.check_demo_video(links, videos_meta, readme_text),
            rubric.check_public_posts(readme_text, links),
            rubric.check_before_after(readme_text),
            rubric.check_failure_run(readme_text, tree_paths),
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


def _repo_name(repo_url: str) -> str | None:
    try:
        return parse_repo_url(repo_url).full_name
    except GitHubError:
        return None


def _usage_dict(llm) -> dict:
    return llm.usage.to_dict() if llm is not None else {"total_tokens": 0, "calls": 0}


async def run_quick_audit(repo_url: str, *, audit_id: str | None = None, run_kind: str = "real",
                          log: StepLog | None = None, llm=None, transport=None,
                          token: str | None = None, ctx: dict | None = None,
                          use_reserve: bool = False) -> dict:
    """Quick phase (~15s, <3k tokens): deterministic checks + score + short verdict/roast.

    `ctx` is filled with what the deep phase needs (README, tree, commits) so it doesn't refetch.
    """
    import time
    import uuid

    from app.agent.loop import template_verdict, write_verdict
    from app.llm import LLM, LLMError, POOL
    from app.scoring import compute_score
    from app.tracing import audit_context

    audit_id = audit_id or uuid.uuid4().hex[:12]
    log = log or StepLog()
    ctx = {} if ctx is None else ctx
    t0 = time.monotonic()
    pool = getattr(llm, "pool", POOL)
    with audit_context(audit_id, run_kind, repo_url, phase="quick"), pool.quick_window(), \
            replay.repo_context(_repo_name(repo_url)):
        report = await run_deterministic_audit(repo_url, token=token, transport=transport, log=log, ctx=ctx)
        score = compute_score(report["checks"])
        if ctx.get("repo_available"):
            llm = llm or LLM(log, deadline=time.monotonic() + 45, priority="high", use_reserve=use_reserve)
            try:
                verdict, source = await write_verdict(
                    llm, score, report, [], purpose="quick_verdict",
                    # one LLM call keeps the quick phase under ~3k tokens; deep phase may rewrite
                    allow_rewrite=config.env("QUICK_ROAST_REWRITE") == "1")
            except LLMError:
                verdict, source = template_verdict(score, report), "template"
        else:
            log.skip("quick_verdict", "repo unavailable; template verdict")
            verdict, source = template_verdict(score, report), "template"

    quick = {"ms": int((time.monotonic() - t0) * 1000), "usage": _usage_dict(llm)}
    report.update(
        audit_id=audit_id, run_kind=run_kind, mode="quick", phase="quick",
        score=score, verdict={**verdict, "source": source},
        phases={"quick": quick, "deep": None},
        usage=quick["usage"], timing_ms={"quick": quick["ms"], "total": quick["ms"]},
        steps=log.to_list(), partial=any(s.status == "failed" for s in log.steps),
    )
    return report


async def run_deep_audit(report: dict, ctx: dict, *, log: StepLog | None = None, llm=None,
                         transport=None, token: str | None = None, use_reserve: bool = False) -> dict:
    """Deep phase (queued): tarball + claims + tool verification + rescore + new verdict."""
    import time

    from app.agent.loop import run_agent
    from app.llm import LLM
    from app.tracing import audit_context

    log = log or StepLog()
    t0 = time.monotonic()
    with audit_context(report["audit_id"], report.get("run_kind", "real"), report["repo_url"], phase="deep"), \
            replay.repo_context(_repo_name(report["repo_url"])):
        if not ctx.get("repo_available"):
            log.skip("deep", "repo unavailable; nothing to verify")
            deep = {"ms": 0, "usage": {"total_tokens": 0, "calls": 0}, "skipped": True}
            report.update(phase="complete", mode="full", steps=log.to_list())
            report["phases"] = {**report.get("phases", {}), "deep": deep}
            return report
        llm = llm or LLM(log, priority="low", use_reserve=use_reserve)
        async with GitHubClient(token=token, transport=transport) as gh:
            agent = await run_agent(report, ctx, log, llm=llm, gh=gh)

    usage = agent.pop("usage") or {"total_tokens": 0, "calls": 0}
    deep = {"ms": int((time.monotonic() - t0) * 1000), "usage": usage}
    agent.pop("agent_ms", None)
    phases = {**report.get("phases", {}), "deep": deep}
    quick = phases.get("quick") or {"ms": 0, "usage": {"total_tokens": 0, "calls": 0}}
    checks = agent.pop("checks", None) or report.get("checks", [])
    # keep the quick score: progress compares quick with quick and deep with deep
    report.setdefault("quick_score", (report.get("score") or {}).get("score"))
    report.update(
        mode="full", phase="complete", checks=checks, summary=rubric.summarize(checks),
        score=agent.pop("score"), verdict=agent.pop("verdict"), agent=agent, phases=phases,
        usage={"total_tokens": quick["usage"].get("total_tokens", 0) + usage.get("total_tokens", 0),
               "calls": quick["usage"].get("calls", 0) + usage.get("calls", 0),
               "quick": quick["usage"], "deep": usage},
        timing_ms={"quick": quick["ms"], "deep": deep["ms"], "total": quick["ms"] + deep["ms"]},
        steps=log.to_list(), partial=any(s.status == "failed" for s in log.steps),
    )
    return report


async def rebuild_context(report: dict, *, transport=None, token: str | None = None) -> dict:
    """Deep phase requested after the quick context expired (or a restart): regather the
    repo data. Deterministic only, no LLM tokens; the quick verdict/score are kept."""
    ctx: dict = {}
    await run_deterministic_audit(report["repo_url"], token=token, transport=transport, log=StepLog(), ctx=ctx)
    return ctx


async def run_full_audit(repo_url: str, *, audit_id: str | None = None, run_kind: str = "real",
                         log: StepLog | None = None, llm=None, transport=None,
                         token: str | None = None) -> dict:
    """Quick then deep, back to back (CLI). The API runs them on separate queues."""
    log = log or StepLog()
    ctx: dict = {}
    report = await run_quick_audit(repo_url, audit_id=audit_id, run_kind=run_kind, log=log, llm=llm,
                                   transport=transport, token=token, ctx=ctx)
    if llm is not None:
        llm.priority = "low"
        llm.usage = type(llm.usage)()  # count deep tokens separately
    return await run_deep_audit(report, ctx, log=log, llm=llm, transport=transport, token=token)
