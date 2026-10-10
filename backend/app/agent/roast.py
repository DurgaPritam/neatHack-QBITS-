"""Roast rules: facts with anchors, stable style per repo, banned phrases, no repeated jokes.

The LLM writes the roast, but code decides what it may say:
- facts come only from the structured results; each has "anchors" (numbers, dates, file
  names, durations). A roast must contain at least one anchor, so it is about THIS repo.
- unknown things are given as unknown; claiming a video is too long or a live link is dead
  without the results saying so is rejected.
- stock phrases are banned, and 5-word overlaps with the last 20 roasts are rejected.
"""
import hashlib
import re
from datetime import datetime

from app.tools.video import MAX_DEMO_SECONDS

STYLES = {
    "sports commentator": "a breathless live sports commentator calling the play-by-play",
    "movie trailer": "a dramatic movie-trailer voiceover ('In a world where...')",
    "food critic": "a snobbish restaurant critic reviewing a tasting menu",
    "strict professor": "a strict professor handing back a marked assignment",
    "Bollywood drama": "a Bollywood melodrama narrator, with a dramatic twist and a song cue",
}

BANNED_PHRASES = [
    "museum exhibit", "broken compass", "ghost town", "about as lively as", "dead battery",
    "magician's rabbit", "time capsule", "went on vacation", "on vacation", "mystery novel",
    "writing cheques", "writing checks", "cheques the commits", "tumbleweed", "crickets",
    "a lot to unpack", "let's be honest", "it's giving", "chef's kiss", "needle in a haystack",
    "swiss cheese", "house of cards", "smoke and mirrors", "all bark and no bite",
    "promises more than it delivers", "bold strategy",
    # style cliches the models reach for every time
    "the crowd is on its feet", "the crowd goes wild", "in a world where", "marked in red ink",
    "see me after class", "michelin", "the replay shows", "ladies and gentlemen",
    "receipts for everything",
]

RECENT_ROASTS = 20
SHINGLE = 5
_TOO_LONG = re.compile(r"too long|over (3|three) min|longer than|marathon|feature[- ]length|runtime", re.I)
_DEAD_VIDEO = re.compile(r"(dead|broken|missing)\W+(\w+\W+){0,3}(video|demo)|(video|demo)\W+(\w+\W+){0,3}(dead|broken|404)", re.I)


def style_for(repo_name: str) -> str:
    """Stable per repo: the same repo always gets the same voice."""
    h = int(hashlib.sha256((repo_name or "").lower().encode()).hexdigest(), 16)
    return list(STYLES)[h % len(STYLES)]


def _date_anchors(iso: str | None) -> list[str]:
    if not iso:
        return []
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return []
    return [d.date().isoformat(), d.strftime("%b %Y"), d.strftime("%B %Y"), str(d.year)]


def _fact(text: str, *anchors) -> dict:
    return {"fact": text, "anchors": [str(a) for a in anchors if a not in (None, "")]}


def build_facts(report: dict, claim_results: list[dict] | None = None) -> list[dict]:
    checks = {c["id"]: c for c in report.get("checks", [])}
    facts: list[dict] = []
    repo = report.get("repo") or {}

    commits = checks.get("commits_in_window")
    if commits and commits["status"] != "unverified":
        m = re.match(r"(\d+) inside, (\d+) before start, (\d+) after close", commits["detail"])
        if m:
            inside, before, after = m.groups()
            facts.append(_fact(f"{inside} commits inside the hackathon window, {before} before it started"
                               + (", only the latest 300 were checked" if "300" in commits["detail"] else ""),
                               *(n for n in (inside, before) if len(n) >= 2 or n != "0"),
                               f"{before} commits", f"{inside} commits"))
    if repo.get("pushed_at"):
        facts.append(_fact(f"last push to the repo: {repo['pushed_at'][:10]}", *_date_anchors(repo["pushed_at"])))
    if repo.get("created_at"):
        facts.append(_fact(f"repo created {repo['created_at'][:10]}", *_date_anchors(repo["created_at"])))

    readme = checks.get("readme_exists")
    if readme:
        m = re.search(r"(\d+) words", readme["detail"])
        if m:
            facts.append(_fact(f"README has {m.group(1)} words", f"{m.group(1)} words", m.group(1)))
    dead = checks.get("dead_links")
    if dead:
        m = re.search(r"(\d+)/(\d+) links dead", dead["detail"])
        if m:
            facts.append(_fact(f"{m.group(1)} of {m.group(2)} README links are dead",
                               f"{m.group(1)}/{m.group(2)}", f"{m.group(1)} of {m.group(2)}", f"{m.group(1)} dead"))
        else:
            n = re.search(r"(\d+) links checked", dead["detail"])
            if n:
                facts.append(_fact(f"all {n.group(1)} checked README links work", f"{n.group(1)} links"))

    video = checks.get("demo_video")
    if video:
        data = video.get("data") or {}
        st = data.get("duration_status")
        if st in ("known", "too_long"):
            facts.append(_fact(f"demo video runs {data['duration']} (limit 3:00)", data["duration"]))
        elif st == "unknown":
            facts.append(_fact(f"demo video link works but its length is UNKNOWN ({data.get('reason')}); "
                               "do not guess its length"))
        elif st == "no_video":
            facts.append(_fact("no demo video link in the README", "no demo video", "no video"))
        elif st == "dead_link":
            facts.append(_fact("the demo video link is dead", "video link is dead"))

    if report.get("files_seen"):
        facts.append(_fact(f"{report['files_seen']} files in the repo", f"{report['files_seen']} files"))
    for path in (report.get("dependency_files") or [])[:2]:
        facts.append(_fact(f"dependency file: {path}", path, path.rsplit("/", 1)[-1]))
    if repo.get("stars"):
        facts.append(_fact(f"{repo['stars']} GitHub stars", f"{repo['stars']} stars", f"{repo['stars']:,}"))

    for r in (claim_results or [])[:8]:
        refs = [e.get("ref", "") for e in r.get("evidence", []) if e.get("ref")]
        files = sorted({re.sub(r":\d+(-\d+)?$", "", ref).rsplit("/", 1)[-1] for ref in refs if "/" in ref or "." in ref})
        quote = (r.get("quote") or r.get("claim") or "")[:80]
        facts.append(_fact(f"README claim \"{quote}\" is {r['status']}"
                           + (f" (evidence: {', '.join(refs[:2])})" if refs else ""), quote, *files[:2]))
    for name in ("neatlogs_sdk", "cfo_ai_plan", "public_posts", "before_after"):
        c = checks.get(name)
        if c and c["status"] in ("fail", "unverified"):
            label = "unknown" if c["status"] == "unverified" else "missing"
            facts.append(_fact(f"{c['title']}: {label} ({c['detail']})"))
    return facts


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _shingles(text: str) -> set[tuple]:
    w = _words(text)
    return {tuple(w[i:i + SHINGLE]) for i in range(len(w) - SHINGLE + 1)}


def _has_anchor(roast: str, anchors: list[str]) -> bool:
    low = roast.lower()
    for a in anchors:
        a_low = a.lower()
        if len(a_low) < 2:
            continue
        if a_low.isdigit():
            if re.search(rf"(?<![\d,.]){re.escape(a_low)}(?![\d])", low):
                return True
        elif a_low in low:
            return True
    return False


def roast_problems(roast: str, facts: list[dict], recent: list[str], report: dict) -> list[str]:
    problems = []
    low = roast.lower()
    banned = [p for p in BANNED_PHRASES if p in low]
    if banned:
        problems.append(f"uses banned stock phrase(s): {', '.join(banned)}")
    anchors = [a for f in facts for a in f["anchors"]]
    if anchors and not _has_anchor(roast, anchors):
        problems.append("doesn't mention any specific fact from the list (a number, date, file name, "
                        "duration or claim quote)")
    fact_shingles = set().union(*(_shingles(f["fact"]) for f in facts)) if facts else set()
    numbers = {w for f in facts for a in f["anchors"] for w in _words(a) if any(ch.isdigit() for ch in w)}
    # quoting a fact (or this repo's numbers) isn't reusing a joke
    mine = {sh for sh in _shingles(roast) - fact_shingles if not numbers.intersection(sh)}
    for old in recent:
        overlap = mine & _shingles(old)
        if overlap:
            problems.append(f"reuses a joke from a recent roast: \"{' '.join(next(iter(overlap)))}\"")
            break
    video = next((c for c in report.get("checks", []) if c["id"] == "demo_video"), None)
    vstatus = ((video or {}).get("data") or {}).get("duration_status")
    if vstatus != "too_long" and _TOO_LONG.search(roast) and re.search(r"video|demo", low):
        problems.append("says the video is too long, but its length is "
                        + ("unknown" if vstatus == "unknown" else "within the limit or not established"))
    if vstatus in ("known", "too_long", "unknown") and _DEAD_VIDEO.search(roast):
        problems.append("calls the demo video dead/broken, but the link works")
    return problems


def template_roast(style: str, facts: list[dict], score: int, variant: int = 0) -> str:
    """Fallback that still follows the rules: styled, factual, no stock phrases, and it varies."""
    anchored = [f for f in facts if f["anchors"]] or [{"fact": f"a score of {score}/100"}]
    fact = anchored[variant % len(anchored)]["fact"]
    openers = {
        "sports commentator": ["Live from the judging arena:", "Play-by-play update:", "Official stat sheet:"],
        "movie trailer": ["Coming soon to a judging table near you:", "This October, one repo dares to ship:",
                          "Rated E for Evidence-free:"],
        "food critic": ["Tonight's tasting menu features", "The amuse-bouche arrives:", "From the chef's table:"],
        "strict professor": ["Grading note:", "Feedback on your submission:", "Office hours reminder:"],
        "Bollywood drama": ["Interval twist:", "Picture abhi baaki hai, because", "Cue the slow-motion rain scene:"],
    }
    closers = ["Judges grade evidence, not intentions.", "The rubric has questions.",
               "Ship the proof before the deadline does.", "That's a lot of trust to ask for."]
    opts = openers.get(style, ["Audit note:"])
    return f"{opts[variant % len(opts)]} {fact}. {closers[(variant // len(opts)) % len(closers)]}"
