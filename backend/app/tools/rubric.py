"""neatHack rubric + deterministic (no-LLM) checks.

Each check returns a dict:
  {id, category, title, status, detail, evidence}
status is one of: pass | warn | fail | unverified
"unverified" means we can't decide deterministically (the LLM pass or a confirmed
convention from the organisers is needed). Scoring is NOT done here (M2).
"""
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath

# Source: neatlogs.com/hackathon
WINDOW_START = datetime(2026, 10, 10, 7, 0, tzinfo=timezone.utc)   # 12:30 IST
WINDOW_END = datetime(2026, 10, 12, 18, 25, tzinfo=timezone.utc)   # 23:55 IST

WEIGHTS = {
    "agent": 0.30,
    "tools": 0.25,              # neatlogs + Entire + cfo.ai
    "demo_video": 0.20,
    "building_in_public": 0.15,
    "usefulness": 0.10,
}

DEPENDENCY_FILES = {
    "requirements.txt", "requirements-dev.txt", "pyproject.toml", "Pipfile",
    "setup.py", "setup.cfg", "package.json", "environment.yml",
}
MAX_DEPENDENCY_FILES = 8

_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|rules)",
    r"disregard\s+(all\s+)?(the\s+)?(previous|prior|above|your)\s+(instructions|prompts|rules)",
    r"(give|award|assign|rate|score)\s+(this|the|our)\s+(repo|repository|project|submission|team)\s+(a\s+)?(score\s+of\s+)?\d{2,3}\s*(/|out\s+of)\s*100",
    r"\b100\s*/\s*100\b",
    r"note\s+(to|for)\s+(the\s+)?(ai|llm|judge|grader|reviewer|model)s?\b",
    r"(you\s+are|act\s+as)\s+(now\s+)?(a|an|the)\s+[\w\s]{0,30}(judge|grader|evaluator)",
    r"(new|updated|override)\s+system\s+prompt",
    r"<\|im_start\|>|\[INST\]|<<SYS>>",
]
_INJECTION_RX = re.compile("|".join(_INJECTION_PATTERNS), re.I)


def _check(id_: str, category: str, title: str, status: str, detail: str,
           evidence: list | None = None, data: dict | None = None) -> dict:
    out = {"id": id_, "category": category, "title": title, "status": status,
           "detail": detail, "evidence": evidence or []}
    if data:
        out["data"] = data
    return out


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _snippets(text: str, rx: re.Pattern, limit: int = 3, width: int = 60) -> list[str]:
    out = []
    for m in rx.finditer(text or ""):
        a, b = max(0, m.start() - width), min(len(text), m.end() + width)
        out.append(" ".join(text[a:b].split()))
        if len(out) >= limit:
            break
    return out


def pick_dependency_files(paths: list[str]) -> list[str]:
    """Shallowest dependency manifests first (skip vendored node_modules etc.)."""
    hits = [
        p for p in paths
        if PurePosixPath(p).name in DEPENDENCY_FILES
        and "node_modules/" not in p and "/vendor/" not in p
    ]
    return sorted(hits, key=lambda p: (p.count("/"), p))[:MAX_DEPENDENCY_FILES]


# ---------------------------------------------------------------- eligibility

def check_repo_public(repo: dict | None, error_kind: str | None) -> dict:
    if repo and not repo.get("private"):
        return _check("repo_public", "eligibility", "Repo is public", "pass",
                      f"{repo['full_name']} is publicly readable")
    reason = {
        "private": "repo is private; judges can't see it",
        "not_found": "repo not found (missing, renamed, or private)",
        "rate_limited": "couldn't check: GitHub rate limit hit",
    }.get(error_kind or "", f"couldn't read repo ({error_kind})")
    status = "unverified" if error_kind in ("rate_limited", "network") else "fail"
    return _check("repo_public", "eligibility", "Repo is public", status, reason)


def check_readme(readme: str | None) -> dict:
    if readme is None:
        return _check("readme_exists", "eligibility", "README exists", "fail", "no README found")
    words = len(readme.split())
    if words < 100:
        return _check("readme_exists", "eligibility", "README exists", "warn",
                      f"README is very thin ({words} words); judges read it first")
    return _check("readme_exists", "eligibility", "README exists", "pass", f"README has {words} words")


def check_commit_window(commits: list[dict] | None, truncated: bool = False) -> dict:
    title = "Commits dated inside the hackathon window"
    if commits is None:
        return _check("commits_in_window", "building_in_public", title, "unverified",
                      "couldn't fetch commits")
    if not commits:
        return _check("commits_in_window", "building_in_public", title, "fail", "repo has no commits")
    before, inside, after = [], [], []
    for c in commits:
        dt = _parse_dt(c.get("committed_at") or c.get("authored_at"))
        if dt is None:
            continue
        (before if dt < WINDOW_START else after if dt > WINDOW_END else inside).append(c)
    days = sorted({_parse_dt(c["committed_at"]).date().isoformat() for c in inside if c.get("committed_at")})
    detail = (f"{len(inside)} inside, {len(before)} before start, {len(after)} after close"
              f"{' (only latest 300 checked)' if truncated else ''}; active days: {', '.join(days) or 'none'}")
    evidence = [f"{c['sha']} {c['committed_at']} {c['message']}" for c in (before[:3] + after[:3])]
    if not inside:
        status = "fail"
    elif before or after:
        status = "warn"  # pre-existing code or post-deadline commits: judges will ask
    elif len(inside) < 5:
        status = "warn"  # too few commits to show building in public
    else:
        status = "pass"
    return _check("commits_in_window", "building_in_public", title, status, detail, evidence)


# ---------------------------------------------------------------- tools

def check_neatlogs_usage(dep_files: dict[str, str], readme: str) -> dict:
    title = "neatlogs SDK is actually used"
    rx = re.compile(r"\bneatlogs\b", re.I)
    in_deps = [p for p, txt in dep_files.items() if rx.search(txt)]
    if in_deps:
        return _check("neatlogs_sdk", "tools", title, "pass",
                      "neatlogs declared as a dependency", in_deps)
    if rx.search(readme or ""):
        return _check("neatlogs_sdk", "tools", title, "warn",
                      "README mentions neatlogs but no dependency file declares it",
                      _snippets(readme, rx, 2))
    return _check("neatlogs_sdk", "tools", title, "fail", "no sign of neatlogs in dependencies or README")


def check_neatlogs_traces(links: list[dict]) -> dict:
    title = "neatlogs trace links"
    traces = [l for l in links if l["kind"] == "neatlogs_trace"]
    if not traces:
        return _check("neatlogs_traces", "tools", title, "fail",
                      "no neatlogs trace links in README (judges expect links or screenshots)")
    dead = [l["url"] for l in traces if l["ok"] is False]
    if dead:
        return _check("neatlogs_traces", "tools", title, "fail", f"{len(dead)} trace link(s) are dead", dead)
    # neatlogs is a SPA: HTTP 200 doesn't prove the trace is publicly viewable.
    return _check("neatlogs_traces", "tools", title, "unverified",
                  f"{len(traces)} trace link(s) reachable; public visibility not confirmed",
                  [l["url"] for l in traces])


def check_entire(tree_paths: list[str], readme: str, links: list[dict]) -> dict:
    """STUB — how Entire checkpoints appear in a repo is not yet confirmed by the organisers.

    TODO(confirm on Discord): replace with the real convention (checkpoint ID format,
    entire-graph output file, link shape). Until then this always returns "unverified"
    and only reports hints it noticed.
    """
    hints = [p for p in tree_paths if re.search(r"(^|/)\.?entire", p, re.I)][:5]
    hints += [l["url"] for l in links if l["kind"] == "entire"][:5]
    hints += _snippets(readme, re.compile(r"\bentire\b.{0,40}(checkpoint|graph)", re.I), 2)
    return _check("entire_checkpoints", "tools", "Entire checkpoints / entire-graph output",
                  "unverified", "STUB: Entire evidence format not yet confirmed; hints listed", hints)


def check_cfo_ai(readme: str, links: list[dict]) -> dict:
    title = "cfo.ai business plan (pricing, costs, revenue, runway)"
    cfo_links = [l for l in links if l["kind"] == "cfo_ai"]
    text = (readme or "").lower()
    topics = [t for t in ("pricing", "cost", "revenue", "runway") if t in text]
    if not cfo_links:
        status = "warn" if "cfo.ai" in text else "fail"
        return _check("cfo_ai_plan", "tools", title, status,
                      "no cfo.ai plan link" + (" (mentioned in text only)" if status == "warn" else ""),
                      topics)
    if any(l["ok"] is False for l in cfo_links):
        return _check("cfo_ai_plan", "tools", title, "fail", "cfo.ai link is dead",
                      [l["url"] for l in cfo_links])
    status = "pass" if len(topics) >= 3 else "warn"
    return _check("cfo_ai_plan", "tools", title, status,
                  f"cfo.ai link present; README covers {len(topics)}/4 of pricing/costs/revenue/runway",
                  [l["url"] for l in cfo_links] + topics)


# ---------------------------------------------------------------- demo video

def check_demo_video(links: list[dict], videos_meta: list[dict] | None = None) -> dict:
    """Pass if a live video is <= 3:00; fail if none, dead, or every known duration is too long;
    unverified (with the reason) when the duration can't be read. Never guesses a length."""
    from app.tools.video import MAX_DEMO_SECONDS, fmt_duration

    title = "Demo video (<= 3 min, covers all three tools)"
    videos = [l for l in links if l["kind"] == "video"]
    if not videos:
        return _check("demo_video", "demo_video", title, "fail", "no YouTube/Loom/Vimeo link in README",
                      data={"duration_status": "no_video"})
    live = [l for l in videos if l["ok"] is not False]
    if not live:
        return _check("demo_video", "demo_video", title, "fail", "video link(s) are dead",
                      [l["url"] for l in videos], data={"duration_status": "dead_link"})
    meta = [m for m in (videos_meta or []) if m["url"] in {l["url"] for l in live}]
    known = [m for m in meta if m["status"] == "known"]
    short = [m for m in known if m["duration_s"] <= MAX_DEMO_SECONDS]
    limit = fmt_duration(MAX_DEMO_SECONDS)
    if short:
        m = min(short, key=lambda v: v["duration_s"])
        return _check("demo_video", "demo_video", title, "pass",
                      f"video is {m['duration']} (limit {limit}); whether it covers all three tools isn't checked",
                      [m["url"]], data={"duration_status": "known", "duration_s": m["duration_s"],
                                        "duration": m["duration"]})
    if known and len(known) == len(meta) and meta:
        m = min(known, key=lambda v: v["duration_s"])
        return _check("demo_video", "demo_video", title, "fail",
                      f"video is {m['duration']}, over the {limit} limit",
                      [m["url"]], data={"duration_status": "too_long", "duration_s": m["duration_s"],
                                        "duration": m["duration"]})
    reason = next((m["reason"] for m in meta if m["status"] == "unknown"), None) or "duration not checked"
    return _check("demo_video", "demo_video", title, "unverified",
                  f"video link live; duration unknown ({reason})",
                  [l["url"] for l in live], data={"duration_status": "unknown", "reason": reason})


# ---------------------------------------------------------------- building in public

def check_public_posts(readme: str, links: list[dict]) -> dict:
    title = "Building-in-public posts tagged #neatHack"
    social = [l["url"] for l in links if l["kind"] == "social" and l["ok"] is not False]
    tagged = bool(re.search(r"#neathack\b", readme or "", re.I))
    if social and tagged:
        return _check("public_posts", "building_in_public", title, "pass",
                      f"{len(social)} social link(s) and #neatHack tag", social)
    if social or tagged:
        missing = "#neatHack tag" if social else "links to the posts"
        return _check("public_posts", "building_in_public", title, "warn", f"missing {missing}", social)
    return _check("public_posts", "building_in_public", title, "fail", "no social posts linked")


# ---------------------------------------------------------------- agent evidence (presence only; LLM verifies in M2)

_BEFORE_AFTER = re.compile(r"\bbefore\b[^\n]{0,120}\bafter\b|\bafter\b[^\n]{0,120}\bbefore\b", re.I)
_NUMBER = re.compile(r"\d+(\.\d+)?\s*(%|ms|s\b|x\b|/\d+)")
_FAILURE = re.compile(r"\b(fail(ed|ure|s)?|retr(y|ied|ies)|fallback|recover(s|ed|y)?|self-heal\w*)\b", re.I)


def check_before_after(readme: str) -> dict:
    title = "Before/after runs with numbers compared"
    hits = _snippets(readme, _BEFORE_AFTER, 3, 40)
    with_numbers = [h for h in hits if _NUMBER.search(h)]
    if with_numbers:
        return _check("before_after", "agent", title, "pass", "before/after comparison with numbers found",
                      with_numbers)
    if hits:
        return _check("before_after", "agent", title, "warn", "before/after mentioned but no numbers", hits)
    return _check("before_after", "agent", title, "fail", "no before/after comparison in README")


def check_failure_run(readme: str) -> dict:
    title = "A run where an action failed and what the agent did next"
    hits = _snippets(readme, _FAILURE, 3, 50)
    if hits:
        return _check("failure_recovery", "agent", title, "unverified",
                      "README talks about failures/recovery; needs LLM + trace verification", hits)
    return _check("failure_recovery", "agent", title, "fail", "no mention of a failure and recovery")


# ---------------------------------------------------------------- hygiene

def check_dead_links(links: list[dict]) -> dict:
    title = "No dead links in README"
    dead = [f"{l['url']} ({l['status'] or l['error']})" for l in links if l["ok"] is False]
    unknown = [l["url"] for l in links if l["ok"] is None]
    if dead:
        return _check("dead_links", "usefulness", title, "fail", f"{len(dead)}/{len(links)} links dead", dead)
    detail = f"{len(links)} links checked" + (f", {len(unknown)} unknown (bot-blocked or local)" if unknown else "")
    return _check("dead_links", "usefulness", title, "pass", detail, unknown)


def check_prompt_injection(texts: dict[str, str]) -> dict:
    """Flag text that tries to instruct the judge. Detection is a feature, not an error."""
    title = "No prompt injection aimed at judges"
    found = []
    for source, text in texts.items():
        for s in _snippets(text, _INJECTION_RX, 3, 40):
            found.append(f"{source}: {s}")
    if found:
        return _check("prompt_injection", "eligibility", title, "fail",
                      f"{len(found)} injection attempt(s) found; ignored and flagged", found[:6])
    return _check("prompt_injection", "eligibility", title, "pass", "no injection patterns found")


def summarize(checks: list[dict]) -> dict:
    counts = {s: 0 for s in ("pass", "warn", "fail", "unverified")}
    for c in checks:
        counts[c["status"]] += 1
    return counts
