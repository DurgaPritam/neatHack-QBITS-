"""neatHack rubric + deterministic (no-LLM) checks.

Each check returns a dict:
  {id, category, title, status, detail, evidence}
status is one of: pass | warn | fail | unverified
"unverified" means we can't decide deterministically (the LLM pass or a confirmed
convention from the organisers is needed). Scoring is NOT done here (M2).
"""
import posixpath
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath
from urllib.parse import urlparse

# Source: neatlogs.com/hackathon
WINDOW_START = datetime(2026, 10, 10, 7, 0, tzinfo=timezone.utc)   # 12:30 IST
WINDOW_END = datetime(2026, 10, 12, 18, 25, tzinfo=timezone.utc)   # 23:55 IST

# Bump when check logic changes: cached audits from an older version are not reused.
CHECKS_VERSION = "2026-10-11.5"

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
                      data={"topics": topics})
    if any(l["ok"] is False for l in cfo_links):
        return _check("cfo_ai_plan", "tools", title, "fail", "cfo.ai link is dead",
                      [l["url"] for l in cfo_links])
    status = "pass" if len(topics) >= 3 else "warn"
    return _check("cfo_ai_plan", "tools", title, status,
                  f"cfo.ai link present; README covers {len(topics)}/4 of pricing/costs/revenue/runway",
                  [l["url"] for l in cfo_links], data={"topics": topics})


# ---------------------------------------------------------------- demo video

_VIDEO_WORDS = re.compile(r"\b(demo|video|walkthrough|screencast)\b", re.I)
_CLOCK = re.compile(r"(?<![\d:])(\d{1,2}):([0-5]\d)(?![\d:])(?!\s*(?:am|pm|ist|utc|gmt)\b)", re.I)
_MIN_SEC = re.compile(r"\b(\d{1,2})\s*(?:m|min|mins|minutes?)\b(?:\s*(?:and\s*)?(\d{1,2})\s*(?:s|sec|secs|seconds?)\b)?", re.I)


def self_reported_length(readme: str) -> tuple[int, str] | None:
    """A demo length the README states on a line about the demo/video ('Demo: 2:45',
    '2 min 45 s video'). -> (seconds, the line), first match."""
    for line in (readme or "").splitlines():
        if not _VIDEO_WORDS.search(line):
            continue
        m = _CLOCK.search(line)
        if m:
            return int(m.group(1)) * 60 + int(m.group(2)), " ".join(line.split())[:160]
        m = _MIN_SEC.search(line)
        if m:
            return int(m.group(1)) * 60 + int(m.group(2) or 0), " ".join(line.split())[:160]
    return None


VIDEO_UNKNOWN_ADVICE = ("Make sure the video is public and mention its length (e.g. 'Demo: 2:45') in your "
                        "README.")


def check_demo_video(links: list[dict], videos_meta: list[dict] | None = None, readme: str = "") -> dict:
    """Pass if a live video is <= 3:00; fail if none, dead, unwatchable (private/removed) or every
    known duration is too long. When the length can't be read, a length stated in the README
    counts as "self-reported"; otherwise the item is not scored (no deduction) and we give advice.
    Never guesses a length, never shows raw tool errors (reasons come from video.FRIENDLY)."""
    from app.tools.video import GONE, MAX_DEMO_SECONDS, fmt_duration

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
                                        "duration": m["duration"], "source": m.get("source")})
    if known and len(known) == len(meta) and meta:
        m = min(known, key=lambda v: v["duration_s"])
        return _check("demo_video", "demo_video", title, "fail",
                      f"video is {m['duration']}, over the {limit} limit",
                      [m["url"]], data={"duration_status": "too_long", "duration_s": m["duration_s"],
                                        "duration": m["duration"], "source": m.get("source")})
    gone = [m for m in meta if m.get("reason_code") in GONE]
    if meta and len(gone) == len(meta):
        return _check("demo_video", "demo_video", title, "fail", f"judges can't watch the video: {gone[0]['reason']}",
                      [m["url"] for m in gone], data={"duration_status": "unwatchable", "reason": gone[0]["reason"],
                                                     "advice": "Make the demo video public (or unlisted) and "
                                                               "check the link in a private browser window."})
    reason = next((m["reason"] for m in meta if m["status"] == "unknown" and m.get("reason")), None) \
        or "We didn't check the video length."
    stated = self_reported_length(readme)
    if stated:
        seconds, line = stated
        if seconds <= MAX_DEMO_SECONDS:
            return _check("demo_video", "demo_video", title, "pass",
                          f"video is {fmt_duration(seconds)} (self-reported in the README; {reason[0].lower()}{reason[1:]})",
                          [l["url"] for l in live] + [line],
                          data={"duration_status": "self_reported", "duration_s": seconds,
                                "duration": fmt_duration(seconds), "reason": reason})
        return _check("demo_video", "demo_video", title, "fail",
                      f"the README says the video is {fmt_duration(seconds)}, over the {limit} limit (self-reported)",
                      [l["url"] for l in live] + [line],
                      data={"duration_status": "too_long", "self_reported": True, "duration_s": seconds,
                            "duration": fmt_duration(seconds)})
    return _check("demo_video", "demo_video", title, "unverified",
                  f"video link works; length unknown: {reason} (not scored)",
                  [l["url"] for l in live],
                  data={"duration_status": "unknown", "reason": reason, "not_scored": True,
                        "advice": VIDEO_UNKNOWN_ADVICE})


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
    """Numbers may sit next to the words or in the table rows that follow a Before | After header."""
    title = "Before/after runs with numbers compared"
    text = readme or ""
    hits = _snippets(text, _BEFORE_AFTER, 3, 40)
    with_numbers = []
    for m in _BEFORE_AFTER.finditer(text):
        window = text[max(0, m.start() - 40):m.end() + 400]
        num = _NUMBER.search(window)
        if num:
            row = window[:num.end() + 20].splitlines()
            with_numbers.append(" ".join(" ".join(row[:1] + row[-1:]).split())[:200])
        if len(with_numbers) >= 3:
            break
    if with_numbers:
        return _check("before_after", "agent", title, "pass", "before/after comparison with numbers found",
                      with_numbers)
    if hits:
        return _check("before_after", "agent", title, "warn", "before/after mentioned but no numbers", hits)
    return _check("before_after", "agent", title, "fail", "no before/after comparison in README")


FAILURE_TITLE = "A run where an action failed and what the agent did next"
FAILURE_ADVICE = ("Describe one real run where a tool or LLM call failed and what the agent did next "
                  "(retry, fallback, partial result), and back it with a trace link or screenshot.")
_EVIDENCE_FILE = re.compile(r"(^|/)(evidence|logs?|traces?|runs?)(/|\.|$)|\.(log|jsonl)$", re.I)


def check_failure_run(readme: str, tree_paths: list[str] | None = None) -> dict:
    """Quick phase: only the README is read, so this can't be judged yet.

    The deep phase (verify_failure_recovery) reads every doc, log and source file. Until
    then, a README that talks about failures, or a repo with evidence docs or logs, isn't
    scored: nobody loses points for what the quick phase can't see.
    """
    hits = _snippets(readme, _FAILURE, 3, 50)
    candidates = [p for p in tree_paths or [] if _EVIDENCE_FILE.search(p)
                  or (PurePosixPath(p).suffix.lower() == ".md" and PurePosixPath(p).name.lower() != "readme.md")]
    if hits or candidates:
        what = "README mentions failures/recovery" if hits else f"{len(candidates)} docs/log files to read"
        return _check("failure_recovery", "agent", FAILURE_TITLE, "unverified",
                      f"{what}; the deep check verifies it (not scored yet)", hits or candidates[:3],
                      data={"not_scored": True, "pending": "deep"})
    return _check("failure_recovery", "agent", FAILURE_TITLE, "fail",
                  "no mention of a failure and recovery, and no docs or logs to check",
                  data={"advice": FAILURE_ADVICE})


# ---------------------------------------------------------------- failure + recovery (deep phase)

_FAIL_WORDS = re.compile(
    r"\b(fail(ed|ure|ures|s|ing)?|errors?|errored|429|5\d\d|rate[- ]limit(ed|s)?|time[sd]?[- ]?out|"
    r"timeouts?|exceptions?|crash(ed|es)?|outage|unavailable|refused|denied)\b", re.I)
_RECOVER_WORDS = re.compile(
    r"\b(retr(y|ied|ies|ying)|fall(s|ing)?[- ]?back|fell back|fallback|back(ed|s|ing)?[- ]?off|"
    r"recover(s|ed|ing)?\b(?!-)|switch(ed|es)? to|rotat(ed|es|ing) to|re-?r[au]n|resum(ed|es)|"
    r"self-heal\w*|partial (report|result)s?|moved (on )?to|waited|cool[- ]?down)\b", re.I)
_RUBRIC_PHRASE = re.compile(r"failures?[- ]?(and|&|\+)[- ]?recover\w*", re.I)  # names the item, describes nothing
_PAST_RUN = re.compile(r"\b(during|failed|errored|crashed|timed out|hit|got|returned|was rate[- ]limited|"
                       r"backed off|fell back|retried|recovered|finished|completed)\b", re.I)
_CONCRETE = re.compile(r"`[^`\n]+`|https?://|\b\d")
_TRACE_URL = re.compile(
    r"https?://[^\s)\]>\"']*(neatlogs\.com/trace|smith\.langchain\.com|langfuse|wandb\.ai|agentops|"
    r"helicone|braintrust|logfire|phoenix|arize)[^\s)\]>\"']*", re.I)
_DOC_IMAGE = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)|<img[^>]+src=[\"']([^\"']+)", re.I)
_CODE_EXT = {".py", ".ts", ".tsx", ".js", ".mjs", ".go", ".rs", ".java", ".kt", ".rb", ".cs", ".php", ".swift"}
_RECOVERY_CODE = re.compile(
    r"(def|function|func|fn|const|let|async def)\s+_?\w*(retry|retries|fallback|fall_back|backoff|recover)\w*|"
    r"@(\w+\.)?retry\b|\btenacity\b|backoff\.on_exception|retry[-_]after|max_retries\s*[=:]\s*[1-9]|"
    r"except\s+[\w.]*(RateLimit|Timeout|APIError|HTTPError)", re.I)
MAX_FAILURE_EVIDENCE = 4


def _is_doc(path: str) -> bool:
    p = PurePosixPath(path)
    return p.suffix.lower() in (".md", ".rst", ".txt", ".adoc") or "docs" in p.parts


def _is_test(path: str) -> bool:
    p = PurePosixPath(path)
    return any(part in ("tests", "test", "__tests__") for part in p.parts) or p.name.startswith("test_")


def _paragraphs(text: str):
    """(first line number, paragraph text, the section that follows) for each blank-line block."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        start = i
        while i < len(lines) and lines[i].strip():
            i += 1
        para = "\n".join(lines[start:i])
        end = start
        while end < len(lines) and end < start + 25 and not (end > start and lines[end].startswith("#")):
            end += 1
        yield start + 1, para, "\n".join(lines[start:end])


def _resolve(doc_path: str, ref: str) -> str:
    """Repo path of an image a doc links to (relative to the doc, or to the root with '/')."""
    ref = ref.split("#")[0].split("?")[0]
    if ref.startswith("/"):
        return posixpath.normpath(ref.lstrip("/"))
    return posixpath.normpath(posixpath.join(posixpath.dirname(doc_path), ref))


def verify_failure_recovery(readme: str, readme_path: str, files: dict[str, str] | None,
                            tree_paths: list[str], claim_results: list[dict] | None = None) -> dict:
    """Deep phase: a failure run counts when it is described (what failed + what the agent
    did next, with a concrete detail) AND backed by independent evidence: a trace link, a
    screenshot that exists in the repo, a log, retry/fallback code, or a verified claim.

    The README can describe the run but never proves it on its own. Deterministic, no LLM.
    """
    if files is None:
        return _check("failure_recovery", "agent", FAILURE_TITLE, "unverified",
                      "couldn't download the repo to check failure handling (not scored)",
                      data={"not_scored": True, "verified_in": "deep"})
    tree = set(tree_paths) | set(files)
    docs = {readme_path or "README.md": readme or ""}
    docs.update({p: t for p, t in files.items() if _is_doc(p) and p != readme_path and not _is_test(p)})

    described, near = [], []
    for path, text in sorted(docs.items(), key=lambda kv: (kv[0] != readme_path, kv[0])):
        for line, para, section in _paragraphs(text):
            plain = _RUBRIC_PHRASE.sub(" ", para)
            if not (_FAIL_WORDS.search(plain) and _RECOVER_WORDS.search(plain) and _CONCRETE.search(plain)):
                continue
            found = [{"kind": "trace link", "ref": m.group(0)} for m in _TRACE_URL.finditer(section)]
            for m in _DOC_IMAGE.finditer(section):
                src = m.group(1) or m.group(2)
                if src.startswith(("http://", "https://")) or _resolve(path, src) in tree:
                    found.append({"kind": "screenshot", "ref": src if src.startswith("http") else _resolve(path, src)})
            described.append({"ref": f"{path}:{line}", "text": " ".join(para.split())[:240],
                              "rank": 2 * bool(found) + len({m.group(0).lower() for m in _PAST_RUN.finditer(plain)})})
            near += found
    # A real run (its own evidence, told in the past tense) beats a description of the mechanism.
    described.sort(key=lambda d: -d.pop("rank"))

    logs, code = [], []
    for path, text in sorted(files.items()):
        if _is_test(path):
            continue
        if _EVIDENCE_FILE.search(path) and not _is_doc(path):
            if _FAIL_WORDS.search(text) and _RECOVER_WORDS.search(text):
                logs.append({"kind": "log", "ref": path})
        elif PurePosixPath(path).suffix.lower() in _CODE_EXT and len(code) < MAX_FAILURE_EVIDENCE:
            for n, l in enumerate(text.splitlines(), 1):
                if _RECOVERY_CODE.search(l):
                    code.append({"kind": "retry/fallback code", "ref": f"{path}:{n}"})
                    break
    claims = [{"kind": "verified claim", "ref": f"claim {r['claim_id']}: {r['claim'][:80]}"}
              for r in claim_results or [] if r.get("status") == "verified"
              and _FAIL_WORDS.search(r.get("claim", "")) and _RECOVER_WORDS.search(r.get("claim", ""))]

    seen, backing = set(), []
    for e in near + logs + claims + code:
        if e["ref"] not in seen:
            seen.add(e["ref"])
            backing.append(e)
    backing = backing[:MAX_FAILURE_EVIDENCE]
    kinds = sorted({e["kind"] for e in backing})
    data = {"verified_in": "deep", "described": described[:3], "backing": backing}
    refs = [d["ref"] for d in described[:2]] + [e["ref"] for e in backing]

    if described and backing:
        return _check("failure_recovery", "agent", FAILURE_TITLE, "pass",
                      f"failure run described in {described[0]['ref']}, backed by {', '.join(kinds)}",
                      refs, data=data)
    if described:
        return _check("failure_recovery", "agent", FAILURE_TITLE, "warn",
                      f"failure run described in {described[0]['ref']}, but no trace link, screenshot, "
                      "log or retry/fallback code backs it", refs,
                      data={**data, "advice": "Back the failure run you describe with evidence a judge can "
                                              "open: a trace link or screenshot of the failed call and the "
                                              "retry/fallback that followed."})
    if backing:
        return _check("failure_recovery", "agent", FAILURE_TITLE, "warn",
                      f"the repo handles failures ({backing[0]['ref']}) but no run is described", refs,
                      data={**data, "advice": "Your code handles failures; now show it. Describe one real "
                                              "run where a call failed and what the agent did next, with "
                                              "a trace link or screenshot."})
    return _check("failure_recovery", "agent", FAILURE_TITLE, "fail",
                  "no described failure run and no retry/fallback code, logs or traces found",
                  data={**data, "advice": FAILURE_ADVICE})


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
