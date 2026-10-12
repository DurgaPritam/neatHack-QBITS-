"""Integrity checks: evidence that doesn't line up with what we can observe. Never scored.

Each signal is a pure function of data the audit already read (plus a few read-only GitHub calls
collected in audit.py) and returns: ok | look ("needs a human look") | unknown ("couldn't check"),
what we checked, the exact reason with evidence links, and how to fix it if it's innocent.
Wording stays neutral on purpose: a mismatch has many innocent causes (rebases, templates, typos).
"""
import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from app import config
from app.tools.rubric import WINDOW_END, WINDOW_START

INTEGRITY_VERSION = "2026-10-12.1"
OK, LOOK, UNKNOWN = "ok", "look", "unknown"
TWITTER_EPOCH_MS = 1288834974657
DISCORD_EPOCH_MS = 1420070400000


def enabled() -> bool:
    return config.env("FEATURE_INTEGRITY", "1").lower() not in ("0", "false", "off", "no")


def _sig(sid: str, title: str, status: str, checked: str, reason: str, evidence=(), fix: str = "") -> dict:
    return {"id": sid, "title": title, "status": status, "checked": checked, "reason": reason,
            "evidence": [e for e in evidence if e][:5], "fix": fix if status != OK else ""}


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _fmt(d: datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M UTC")


def snowflake_time(sid: int, epoch_ms: int) -> datetime:
    return datetime.fromtimestamp(((sid >> 22) + epoch_ms) / 1000, tz=timezone.utc)


# ---------------------------------------------------------------- 1 + 2: post / message dates

_X_STATUS = re.compile(r"^https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/[^/]+/status(?:es)?/(\d{6,25})", re.I)
_DISCORD_MSG = re.compile(r"^https?://(?:www\.|ptb\.|canary\.)?discord(?:app)?\.com/channels/[\d@me]+/\d+/(\d{6,25})", re.I)


def _window_dates(sid, title, urls, rx, epoch, what, fix):
    found = [(u, snowflake_time(int(m.group(1)), epoch)) for u in urls if (m := rx.match(u))]
    if not found:
        return _sig(sid, title, OK, f"{what} links in the README", f"No {what} links to check.")
    outside = [(u, d) for u, d in found if d < WINDOW_START or d > WINDOW_END]
    if not outside:
        return _sig(sid, title, OK, f"{len(found)} {what} link(s): date decoded from the ID",
                    f"All {len(found)} are dated inside the hackathon window.")
    return _sig(sid, title, LOOK, f"{len(found)} {what} link(s): date decoded from the ID",
                "; ".join(f"{_fmt(d)} ({'before the start' if d < WINDOW_START else 'after the close'})"
                          for _, d in outside[:3]),
                [u for u, _ in outside], fix)


def x_post_dates(urls: list[str]) -> dict:
    return _window_dates("x_post_dates", "X post dates", urls, _X_STATUS, TWITTER_EPOCH_MS, "X/Twitter post",
                         "If a post from before the hackathon is context (an idea or a teaser), label it as such "
                         "in the README; building-in-public posts should come from the window.")


def discord_dates(urls: list[str]) -> dict:
    return _window_dates("discord_dates", "Discord message dates", urls, _DISCORD_MSG, DISCORD_EPOCH_MS,
                         "Discord message", "If an older message is context, say so next to the link.")


# ---------------------------------------------------------------- 3: demo video date

def video_dates(videos: list[dict]) -> dict:
    title = "Demo video publish date"
    yt = [v for v in videos or [] if "youtu" in (v.get("url") or "")]
    if not yt:
        return _sig("video_date", title, OK, "YouTube demo videos", "No YouTube demo video to check.")
    known = [(v["url"], _dt(v.get("published_at"))) for v in yt if v.get("published_at")]
    if not known:
        return _sig("video_date", title, UNKNOWN, "publish date from the YouTube Data API",
                    "The YouTube Data API didn't give a publish date (quota, private video or API off), so we "
                    "couldn't confirm it.", [v["url"] for v in yt],
                    "Nothing to fix; we'll check again on the next audit.")
    early = [(u, d) for u, d in known if d and d < WINDOW_START]
    if early:
        return _sig("video_date", title, LOOK, "publish date from the YouTube Data API",
                    "; ".join(f"published {_fmt(d)}, before the hackathon started" for _, d in early),
                    [u for u, _ in early],
                    "If this is an older video reused as context, link the demo you recorded for neatHack instead.")
    return _sig("video_date", title, OK, "publish date from the YouTube Data API",
                f"Published inside or after the window ({_fmt(known[0][1])}).")


# ---------------------------------------------------------------- 4: links point to this repo

_ENTIRE_REPO = re.compile(r"^https?://(?:www\.)?entire\.io/gh/([^/\s]+)/([^/\s#?]+)", re.I)
_GH_CODE = re.compile(r"^https?://(?:www\.)?github\.com/([^/\s]+)/([^/\s#?]+)/(commit|blob|tree)/", re.I)


def links_this_repo(urls: list[str], full_name: str) -> dict:
    title = "Evidence links point to this repo"
    me = (full_name or "").lower().removesuffix(".git")
    checked, foreign = 0, []
    for u in urls:
        m = _ENTIRE_REPO.match(u) or _GH_CODE.match(u)
        if not m:
            continue
        checked += 1
        repo = f"{m.group(1)}/{m.group(2)}".lower().removesuffix(".git")
        if repo != me:
            foreign.append(u)
    if not checked:
        return _sig("links_this_repo", title, OK, "entire.io and GitHub commit/file links",
                    "No entire.io or GitHub commit/file links to compare.")
    if not foreign:
        return _sig("links_this_repo", title, OK, f"{checked} entire.io / GitHub commit or file link(s)",
                    f"All point to {full_name}.")
    return _sig("links_this_repo", title, LOOK, f"{checked} entire.io / GitHub commit or file link(s)",
                f"{len(foreign)} point to a different repo than {full_name}.", foreign,
                "If the work moved from another repo (a fork or an earlier repo), say so in the README and "
                "link this repo's commits and checkpoints too.")


def foreign_entire_links(integrity: dict | None) -> set[str]:
    sig = next((s for s in (integrity or {}).get("signals", []) if s["id"] == "links_this_repo"), None)
    return {u for u in (sig or {}).get("evidence", []) if "entire.io" in u} if sig and sig["status"] == LOOK else set()


# ---------------------------------------------------------------- 5: Entire checkpoints are real

_CP_ID = re.compile(r"\b([0-9A-HJKMNP-TV-Z]{26}|[0-9a-f]{12})\b")
_CP_CONTEXT = re.compile(r"checkpoint|entire", re.I)


def checkpoints_real(readme: str, ref_ids: list[str] | None, commits: list[dict] | None, refs_more: bool = False) -> dict:
    title = "Entire checkpoint IDs are real"
    mentioned = []
    for line in (readme or "").splitlines():
        if _CP_CONTEXT.search(line):
            mentioned += [i for i in _CP_ID.findall(line) if not re.fullmatch(r"[0-9a-f]{12}", i) or "checkpoint" in line.lower()]
    mentioned = list(dict.fromkeys(mentioned))
    if not mentioned:
        return _sig("checkpoints_real", title, OK, "checkpoint IDs quoted in the README", "No checkpoint IDs quoted.")
    if ref_ids is None and commits is None:
        return _sig("checkpoints_real", title, UNKNOWN, "checkpoint refs and commit trailers",
                    "Couldn't read the repo's checkpoint refs or commits.", fix="Nothing to fix; try again later.")
    tagged = {c["checkpoint"]: c for c in commits or [] if c.get("checkpoint")}
    known = set(ref_ids or []) | set(tagged)
    missing = [i for i in mentioned if i not in known]
    outside = []
    for i in mentioned:
        c = tagged.get(i)
        d = _dt((c or {}).get("committed_at") or (c or {}).get("authored_at"))
        if d and not (WINDOW_START <= d <= WINDOW_END):
            outside.append(f"{i} (commit {c['sha'][:7]}, {_fmt(d)})")
    if missing and refs_more:
        return _sig("checkpoints_real", title, UNKNOWN, f"{len(mentioned)} checkpoint ID(s) vs pushed refs",
                    "The repo has more checkpoint refs than we can list, so a missing ID may just be beyond the page.",
                    missing, "Nothing to fix.")
    if missing or outside:
        parts = ([f"{len(missing)} quoted ID(s) aren't in this repo's pushed checkpoint refs or commit trailers: "
                  + ", ".join(missing[:3])] if missing else []) + \
                ([f"commit dated outside the window: {', '.join(outside[:2])}"] if outside else [])
        return _sig("checkpoints_real", title, LOOK, f"{len(mentioned)} checkpoint ID(s) vs pushed refs and trailers",
                    "; ".join(parts), [],
                    "Push your checkpoints (`git push` with Entire's pre-push hook, or push refs/entire/*) and "
                    "quote IDs from this repo.")
    return _sig("checkpoints_real", title, OK, f"{len(mentioned)} checkpoint ID(s) vs pushed refs and trailers",
                "Every quoted checkpoint exists in this repo and is dated inside the window.")


# ---------------------------------------------------------------- 6: commit dates vs push times

def push_times(commits: list[dict] | None, events: list[dict] | None) -> dict:
    title = "Commit dates vs push times"
    if events is None:
        return _sig("push_times", title, UNKNOWN, "GitHub's public push events",
                    "Couldn't read the repo's public events.", fix="Nothing to fix.")
    pushed: dict[str, datetime] = {}
    order = [c["sha"][:12] for c in commits or []]          # newest first, as GitHub lists them

    def mark(sha: str, at: datetime) -> None:
        if sha and (sha not in pushed or at < pushed[sha]):
            pushed[sha] = at
    for e in events:
        if e.get("type") != "PushEvent" or not (at := _dt(e.get("created_at"))):
            continue
        payload = e.get("payload") or {}
        for c in payload.get("commits") or []:             # older payloads list the commits
            mark((c.get("sha") or "")[:12], at)
        head, before = (payload.get("head") or "")[:12], (payload.get("before") or "")[:12]
        if head in order:                                    # newer payloads: everything after `before` up to `head`
            start = order.index(head)
            end = order.index(before) if before in order else min(start + 1, len(order))
            for sha in order[start:max(end, start + 1)]:
                mark(sha, at)
    inside = [c for c in commits or [] if (d := _dt(c.get("committed_at") or c.get("authored_at")))
              and WINDOW_START <= d <= WINDOW_END]
    matched = [(c, pushed[c["sha"][:12]]) for c in inside if c["sha"][:12] in pushed]
    if not matched:
        return _sig("push_times", title, UNKNOWN, "GitHub's public push events (last ~90 days, may be incomplete)",
                    "No push events matched the commits, so we couldn't compare.", fix="Nothing to fix.")
    early = [(c, at) for c, at in matched if at < WINDOW_START]
    checked = f"{len(matched)} of {len(inside)} in-window commits matched to a push event"
    if early:
        return _sig("push_times", title, LOOK, checked,
                    "; ".join(f"commit {c['sha'][:7]} is dated {c.get('committed_at')} but was pushed {_fmt(at)}, "
                              "before the hackathon started" for c, at in early[:3]), [],
                    "If you rebased or amended commits (which rewrites their dates), say so in the README.")
    return _sig("push_times", title, OK, checked, "Every matched commit was pushed after the hackathon started.")


# ---------------------------------------------------------------- 7: code dump

_TEMPLATE = re.compile(r"\b(template|boilerplate|starter( kit)?|scaffold(ed|ing)?|forked from|based on|bootstrapped with|"
                       r"create-react-app|create-next-app|cookiecutter|pre-existing code|started from)\b", re.I)


def code_dump(stats: list[dict] | None, readme: str, share: float = 0.7, min_lines: int = 2000) -> dict:
    title = "No single commit adds most of the code"
    if stats is None:
        return _sig("code_dump", title, UNKNOWN, "lines added per commit",
                    "Too many commits to fetch line counts for, or GitHub didn't return them.", fix="Nothing to fix.")
    total = sum(max(0, s.get("additions") or 0) for s in stats)
    if total < min_lines or not stats:
        return _sig("code_dump", title, OK, f"lines added in {len(stats)} commit(s)",
                    f"{total} lines added in total: too small to judge.")
    big = max(stats, key=lambda s: s.get("additions") or 0)
    frac = (big.get("additions") or 0) / total
    d = _dt(big.get("date"))
    in_window = d is not None and WINDOW_START <= d <= WINDOW_END
    checked = f"lines added in {len(stats)} commit(s), {total:,} in total"
    if frac > share and in_window:
        if _TEMPLATE.search(readme or ""):
            return _sig("code_dump", title, OK, checked,
                        f"Commit {big['sha'][:7]} adds {frac:.0%} of the lines, and the README says the project "
                        "started from a template or existing code.")
        return _sig("code_dump", title, LOOK, checked,
                    f"One commit ({big['sha'][:7]}, {_fmt(d)}) adds {big['additions']:,} lines, {frac:.0%} of everything "
                    "added.", [],
                    "If you started from a template or existing code, say so in the README; if you squashed your work, "
                    "mention it.")
    return _sig("code_dump", title, OK, checked, f"The largest commit adds {frac:.0%} of the lines.")


# ---------------------------------------------------------------- 8: dates before the repo existed

def before_created(commits: list[dict] | None, created_at: str | None, readme: str = "") -> dict:
    title = "Commit dates vs repo creation"
    created = _dt(created_at)
    if created is None or commits is None:
        return _sig("before_created", title, UNKNOWN, "commit dates vs repo created_at",
                    "Couldn't read the repo's creation date or commits.", fix="Nothing to fix.")
    early = [c for c in commits if (d := _dt(c.get("committed_at") or c.get("authored_at"))) and d < created
             and WINDOW_START <= d]   # history imported from before the window is the commit-window check's job
    early_in_window = [c for c in early if WINDOW_START <= _dt(c.get("committed_at") or c.get("authored_at")) <= WINDOW_END]
    if not early_in_window:
        return _sig("before_created", title, OK, f"{len(commits)} commit dates vs created_at ({_fmt(created)})",
                    "No in-window commit is dated before the repo was created.")
    if re.search(r"\b(imported|moved|migrated|copied) (from|over)|\bnew repo\b|\brenamed\b", readme or "", re.I):
        return _sig("before_created", title, OK, f"{len(commits)} commit dates vs created_at ({_fmt(created)})",
                    "Some commits predate the repo, and the README says the history was moved from another repo.")
    return _sig("before_created", title, LOOK, f"{len(commits)} commit dates vs created_at ({_fmt(created)})",
                f"{len(early_in_window)} commit(s) are dated after the hackathon started but before this repo was "
                f"created, e.g. {early_in_window[0]['sha'][:7]} ({early_in_window[0].get('committed_at')}).", [],
                "If you moved the history from another repo, say so in the README (that's fine).")


# ---------------------------------------------------------------- 9: screenshots

_MAGIC = {b"\x89PNG\r\n\x1a\n": "png", b"\xff\xd8\xff": "jpeg", b"GIF8": "gif", b"RIFF": "webp"}
MIN_IMAGE_BYTES = 8_000


def image_kind(data: bytes) -> str | None:
    for magic, kind in _MAGIC.items():
        if data.startswith(magic) and (kind != "webp" or data[8:12] == b"WEBP"):
            return kind
    return None


def png_size(data: bytes) -> tuple[int, int] | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return None


def screenshots(images: list[dict] | None) -> dict:
    """images: [{src, exists, bytes (None if unreadable), size}] for README trace/evidence images."""
    title = "Evidence screenshots are real images"
    if images is None:
        return _sig("screenshots", title, UNKNOWN, "README evidence images", "Couldn't read the images.", fix="Nothing to fix.")
    if not images:
        return _sig("screenshots", title, OK, "README evidence images", "No trace or evidence screenshots to check.")
    problems, hashes = [], {}
    for im in images:
        data = im.get("bytes")
        if not im.get("exists"):
            problems.append(f"{im['src']}: not in the repo")
            continue
        if data is None:
            continue
        kind = image_kind(data)
        if not kind:
            problems.append(f"{im['src']}: not an image file")
            continue
        if len(data) < MIN_IMAGE_BYTES:
            problems.append(f"{im['src']}: only {len(data):,} bytes")
        dims = png_size(data)
        if dims and (dims[0] < 200 or dims[1] < 100):
            problems.append(f"{im['src']}: {dims[0]}×{dims[1]} px")
        hashes.setdefault(hashlib.sha256(data).hexdigest(), []).append(im["src"])
    for files in hashes.values():
        if len(files) > 1:
            problems.append(f"the same image is used as {len(files)} different screenshots: {', '.join(files[:3])}")
    unread = [im for im in images if im.get("exists") and im.get("bytes") is None]
    checked = f"{len(images)} README evidence image(s): exists, image type, size, duplicates"
    if problems:
        return _sig("screenshots", title, LOOK, checked, "; ".join(problems[:4]), [im["src"] for im in images][:5],
                    "Use a real, full-size screenshot of each trace (one file per run).")
    if unread and len(unread) == len(images):
        return _sig("screenshots", title, UNKNOWN, checked, "Couldn't download the images.", fix="Nothing to fix.")
    return _sig("screenshots", title, OK, checked, "Every evidence image exists, is a real image and is distinct.")


# ---------------------------------------------------------------- 10: before/after math

_NUM = r"(-?\d[\d,]*(?:\.\d+)?)"
_ROW_PCT = re.compile(r"(-?\d+(?:\.\d+)?)\s?%\s*(faster|slower|fewer|less|more|lower|higher|cheaper|smaller|"
                      r"reduction|decrease|increase|improvement|drop|cut|saved?)", re.I)
_ROW_X = re.compile(r"(\d+(?:\.\d+)?)\s?[x×]\s*(faster|fewer|less|more|cheaper|smaller|lower|higher|reduction)?", re.I)


def _nums(cell: str) -> list[float]:
    return [float(n.replace(",", "")) for n in re.findall(_NUM, cell or "")]


def before_after_math(readme: str) -> dict:
    """In tables with Before and After columns, a stated % change or N× must match the two numbers
    (±2 percentage points, or ±10% for multipliers). Rows we can't parse are skipped, never flagged."""
    title = "Before/after numbers add up"
    lines = (readme or "").splitlines()
    checked, wrong = 0, []
    i = 0
    while i < len(lines):
        head = [c.strip().lower() for c in lines[i].strip().strip("|").split("|")]
        if lines[i].strip().startswith("|") and any("before" in h for h in head) and any("after" in h for h in head):
            bi = next(k for k, h in enumerate(head) if "before" in h)
            ai = next(k for k, h in enumerate(head) if "after" in h)
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
                if len(cells) > max(bi, ai):
                    b, a = _nums(cells[bi]), _nums(cells[ai])
                    rest = " ".join(c for k, c in enumerate(cells) if k not in (bi,))
                    if len(b) >= 1 and len(a) >= 1 and b[0] != 0:
                        bv, av = b[0], a[0]
                        for m in _ROW_PCT.finditer(rest):
                            stated = float(m.group(1))
                            actual = abs(av - bv) / abs(bv) * 100
                            checked += 1
                            if abs(abs(stated) - actual) > 2:
                                wrong.append(f"{cells[0][:40]}: {bv:g} → {av:g} is {actual:.0f}%, the table says {stated:g}%")
                        for m in _ROW_X.finditer(rest):
                            stated = float(m.group(1))
                            if stated < 1.1 or av == 0:
                                continue
                            actual = max(bv, av) / min(bv, av) if min(bv, av) > 0 else 0
                            checked += 1
                            if actual and abs(stated - actual) / actual > 0.1:
                                wrong.append(f"{cells[0][:40]}: {bv:g} → {av:g} is {actual:.1f}×, the table says {stated:g}×")
                j += 1
            i = j
        else:
            i += 1
    if not checked:
        return _sig("before_after_math", title, OK, "before/after tables with a stated % or ×",
                    "No stated percentages or multipliers to check.")
    if wrong:
        return _sig("before_after_math", title, LOOK, f"{checked} stated change(s) in before/after tables",
                    "; ".join(wrong[:3]), [], "Recompute the change from the two numbers (or fix the numbers).")
    return _sig("before_after_math", title, OK, f"{checked} stated change(s) in before/after tables",
                "Every stated % or × matches its before and after numbers.")


# ---------------------------------------------------------------- 11 (admin only): README fingerprints

def fingerprint(text: str, k: int = 5, size: int = 64) -> list[int]:
    """MinHash of word 5-shingles: Jaccard similarity ≈ share of equal positions."""
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    shingles = {" ".join(words[i:i + k]) for i in range(max(0, len(words) - k + 1))}
    if len(shingles) < 20:
        return []
    out = []
    for seed in range(size):
        out.append(min(int.from_bytes(hashlib.blake2b(f"{seed}:{s}".encode(), digest_size=8).digest(), "big")
                       for s in shingles))
    return out


def similarity(a: list[int], b: list[int]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x == y for x, y in zip(a, b)) / len(a)


# ---------------------------------------------------------------- all together

def evaluate(*, readme: str, urls: list[str], full_name: str, created_at: str | None, commits: list[dict] | None,
             ref_ids: list[str] | None, refs_more: bool, videos: list[dict], events: list[dict] | None,
             stats: list[dict] | None, images: list[dict] | None) -> dict:
    signals = [
        x_post_dates(urls), discord_dates(urls), video_dates(videos), links_this_repo(urls, full_name),
        checkpoints_real(readme, ref_ids, commits, refs_more), push_times(commits, events),
        code_dump(stats, readme), before_created(commits, created_at, readme), screenshots(images),
        before_after_math(readme),
    ]
    counts = {s: sum(x["status"] == s for x in signals) for s in (OK, LOOK, UNKNOWN)}
    return {"version": INTEGRITY_VERSION, "signals": signals, "counts": counts, "scored": False}
