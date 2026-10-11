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
from urllib.parse import urlparse

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


_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)|<img\b[^>]*\bsrc=[\"']([^\"']+)", re.I)
_TRACE_WORDS = re.compile(r"neatlogs|trace", re.I)
_LOGIN_PATH = re.compile(r"^/(auth|login|signin|sign-in)\b", re.I)


def trace_screenshots(readme: str, tree_paths: list[str] | None = None, links: list[dict] | None = None) -> list[str]:
    """README-embedded images whose alt text or path mentions neatlogs/trace and that actually
    exist: a relative path must be a file in the repo, a URL must not be a dead link."""
    files = {p.lower() for p in tree_paths or []}
    dead = {l["url"] for l in links or [] if l["ok"] is False}
    out = []
    for m in _IMAGE.finditer(readme or ""):
        alt, src = m.group(1) or "", m.group(2) or m.group(3) or ""
        if not (_TRACE_WORDS.search(alt) or _TRACE_WORDS.search(src)):
            continue
        if src.startswith(("http://", "https://")):
            ok = src not in dead
        else:
            ok = src.split("#")[0].split("?")[0].lstrip("./").lower() in files
        if ok:
            out.append(src)
    return out[:5]


def needs_login(link: dict) -> bool:
    """neatlogs answers a logged-out visitor with a redirect to /auth?intent=signin (or a 401)."""
    final = urlparse(link.get("final_url") or link["url"])
    return (bool(_LOGIN_PATH.search(final.path or "")) or "callbackUrl=" in (final.query or "")
            or link.get("status") == 401)


def check_neatlogs_traces(links: list[dict], readme: str = "", tree_paths: list[str] | None = None) -> dict:
    title = "neatlogs trace links"
    traces = [l for l in links if l["kind"] == "neatlogs_trace"]
    shots = trace_screenshots(readme, tree_paths, links)
    if not traces:
        if shots:
            return _check("neatlogs_traces", "tools", title, "pass",
                          f"{len(shots)} trace screenshot(s) embedded in the README", shots)
        return _check("neatlogs_traces", "tools", title, "fail",
                      "no neatlogs trace links in README (judges expect links or screenshots)")
    login = [l for l in traces if needs_login(l)]
    dead = [l["url"] for l in traces if l["ok"] is False and l not in login]
    if dead:
        return _check("neatlogs_traces", "tools", title, "fail", f"{len(dead)} trace link(s) are dead", dead)
    if login:
        urls = [l["url"] for l in login]
        if shots:
            return _check("neatlogs_traces", "tools", title, "pass",
                          f"{len(login)} trace link(s) need a neatlogs login, but the README embeds "
                          f"{len(shots)} trace screenshot(s)", urls + shots, data={"visibility": "login_required"})
        advice = ("Your neatlogs trace links are found, but not publicly viewable (they redirect to a "
                  "login page). Add screenshots of the traces to the README or use a public share link.")
        return _check("neatlogs_traces", "tools", title, "warn",
                      f"{len(login)} trace link(s) found, but not publicly viewable: add screenshots "
                      "or a public share link", urls, data={"visibility": "login_required", "advice": advice})
    public = [l["url"] for l in traces if l["ok"] is True]
    if public:
        return _check("neatlogs_traces", "tools", title, "pass",
                      f"{len(public)} trace link(s) open without a login redirect", public,
                      data={"visibility": "public"})
    return _check("neatlogs_traces", "tools", title, "unverified",
                  f"{len(traces)} trace link(s); neatlogs didn't answer, so visibility is unknown",
                  [l["url"] for l in traces])


_CHECKPOINT_ID = re.compile(r"[0-9a-f]{12}|[0-9A-HJKMNP-TV-Z]{26}")  # branch backend | ref backend (ULID)
_ENTIRE_ADVICE = ("Commit with Entire enabled (answer yes when it asks to link the commit), push so the "
                  "checkpoints reach GitHub, then put a checkpoint link "
                  "(https://entire.io/gh/OWNER/REPO/commit/FULL_SHA) and its checkpoint ID in the README.")


def check_entire(tree_paths: list[str], readme: str, links: list[dict], commits: list[dict] | None = None,
                 refs: dict | None = None, repo_full_name: str = "") -> dict:
    """Entire evidence, strongest first (format per docs.entire.io + hack.entire.io/neathacks-2026):
    - commits carrying an `Entire-Checkpoint: <id>` trailer (12-hex or 26-char ULID ids)
    - pushed checkpoint storage: refs/entire/checkpoints/<shard>/<id> or the entire/checkpoints/v1 branch
    - a checkpoint link in the README: https://entire.io/gh/OWNER/REPO/commit/SHA (+ the ID)
    The README alone never proves a checkpoint exists. When nothing is found in git we can't be sure
    (unpushed refs, a failed lookup), so the result is "unverified" and not scored (no deduction).
    """
    title = "Entire checkpoints / entire-graph output"
    tagged = [c for c in commits or [] if c.get("checkpoint")]
    ref_ids = [i for i in (refs or {}).get("ids") or [] if _CHECKPOINT_ID.fullmatch(i)]
    branch = (refs or {}).get("branch")
    known = {c["checkpoint"] for c in tagged} | set(ref_ids)
    repo_path = f"/gh/{repo_full_name.lower()}/" if repo_full_name else None
    cp_links = [l for l in links if l["kind"] == "entire" and (
        (repo_path and repo_path in l["url"].lower()) or "checkpoint" in l["url"].lower()
        or any(i in l["url"] for i in known))]
    readme_ids = sorted(i for i in known if i in (readme or ""))
    config_files = [p for p in tree_paths if p.startswith(".entire/")][:5]

    found = []
    if tagged:
        found.append(f"{len(tagged)} commit(s) carry an Entire-Checkpoint trailer")
    if ref_ids:
        found.append(f"{len(ref_ids)}{'+' if (refs or {}).get('more') else ''} checkpoint ref(s) pushed")
    elif (refs or {}).get("ids"):  # other layouts (e.g. refs/entire/checkpoints/v2/...)
        found.append(f"{len(refs['ids'])}{'+' if refs.get('more') else ''} checkpoint storage ref(s) pushed")
    if branch:
        found.append(f"checkpoint branch {branch} pushed")
    example = None
    if tagged and repo_full_name:
        c = tagged[0]
        example = f"https://entire.io/gh/{repo_full_name}/commit/{c['full_sha']} (checkpoint {c['checkpoint']})"
    data = {"checkpoint_ids": sorted(known)[:10], "readme_ids": readme_ids}

    if found:
        evidence = ([f"{c['sha']} Entire-Checkpoint: {c['checkpoint']}" for c in tagged[:3]]
                    + [l["url"] for l in cp_links][:3])
        live = [l for l in cp_links if l["ok"] is not False]
        if live or readme_ids:
            shown = []
            if live:
                shown.append(f"{len(live)} checkpoint link(s)")
            if readme_ids:
                shown.append(f"checkpoint ID {readme_ids[0]} that matches the repo")
            return _check("entire_checkpoints", "tools", title, "pass",
                          "; ".join(found) + "; README shows " + " and ".join(shown), evidence, data)
        if cp_links:
            fix = example or "https://entire.io/gh/OWNER/REPO/commit/FULL_SHA"
            return _check("entire_checkpoints", "tools", title, "warn",
                          "; ".join(found) + "; but the README's checkpoint link is dead", evidence,
                          {**data, "advice": f"Your Entire checkpoint link is dead; replace it with {fix}."})
        advice = ("Entire checkpoints are in your git history, but the README doesn't link one. Add a "
                  "checkpoint link and its ID" + (f", e.g. {example}" if example else "") + ".")
        return _check("entire_checkpoints", "tools", title, "warn",
                      "; ".join(found) + "; README has no checkpoint link or ID (judges ask for both)",
                      evidence, {**data, "advice": advice})

    # Nothing in git isn't proof of absence (unpushed refs, a failed lookup): don't deduct.
    hints = [*config_files, *[l["url"] for l in cp_links][:3],
             *_snippets(readme, re.compile(r"\bentire\b.{0,40}(checkpoint|graph)", re.I), 2)]
    if refs is None and commits is None:
        why = "couldn't read commits or checkpoint refs"
    elif hints:
        why = "Entire is mentioned or configured, but no checkpoints were found in pushed commits or refs"
    else:
        why = "no Entire checkpoints found in commits, refs or the README"
    return _check("entire_checkpoints", "tools", title, "unverified",
                  f"couldn't verify automatically: {why} (not scored)", hints,
                  {**data, "not_scored": True, "advice": _ENTIRE_ADVICE})


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
