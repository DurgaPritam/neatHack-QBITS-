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
SHINGLE = 8           # only long repeated phrases count as a reused joke
STOPWORDS = set("""a an the and or but of to in on at for with by from as is are was were be been it its
this that these those there here we you your our they their i me my he she his her them us so very
just than then too not no all any some more most such what which who whom how when where why do does
did has have had will would can could should into out up down over under again only own same""".split())
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
        elif st == "self_reported":
            facts.append(_fact(f"the README says the demo video is {data['duration']} (we couldn't time it "
                               "ourselves)", data["duration"]))
        elif st == "unwatchable":
            facts.append(_fact("the demo video can't be watched (private or removed)", "private", "removed"))
        elif st == "unknown":
            facts.append(_fact("demo video link works but its length is UNKNOWN; do not guess its length "
                               "and do not call it missing"))
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


def _joke_shingles(text: str, facts: list[dict]) -> set[tuple]:
    """5-word phrases that could carry a joke: not mostly stopwords, not about this repo's facts.

    Common phrasing ("we are live at the") and fact wording ("commits inside the hackathon
    window", "12:46") are shared by any honest roast; a distinctive turn of phrase is not.
    """
    fact_words = {w for f in facts for w in _words(f["fact"]) if w not in STOPWORDS}
    fact_words |= {w for f in facts for a in f["anchors"] for w in _words(a)}
    if "0" in {w for f in facts for w in _words(f["fact"])}:
        fact_words |= {"zero", "none", "0"}  # "zero commits" restates the fact "0 commits"
    out = set()
    for sh in _shingles(text):
        content = [w for w in sh if w not in STOPWORDS]
        if len(content) < 3:
            continue
        if sum(w in fact_words for w in content) >= len(content) - 1:
            continue
        out.add(sh)
    return out


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
    mine = _joke_shingles(roast, facts)
    for old in recent:
        overlap = mine & _shingles(old)  # old side unfiltered: any shared distinctive phrase counts
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


# ---------------------------------------------------------------- fact-only (template) roasts
#
# Used when the Groq budget is low or the LLM's roast fails the fact check, so they have to be
# funny on their own. Slots are filled from the structured results only:
#   {stat}   the most interesting big number ("37 commits pushed before the hackathon even started")
#   {score}  the score;  {miss} the biggest missing item, {miss_pts} the points it would add
#   {date}   last push, only when it was before the hackathon started
#   {video}  demo length, only when it is over the 3:00 limit
# Every template uses at least one of stat/date/video, which carry the fact-check anchors.

TEMPLATES: dict[str, list[str]] = {
    "sports commentator": [
        "And it's {stat}! The scoreboard reads {score}/100, and the coach is still looking for {miss}.",
        "What a stat line: {stat}. Sadly the referee only counts what's on the rubric, and {miss} is "
        "still warming the bench. Final whistle: {score}/100.",
        "{video} on the clock for a demo video! The limit is 3:00, folks; this team is playing extra time "
        "nobody asked for. Scoreboard: {score}/100.",
        "Last touch on the ball: {date}. Since then the team has been sitting in the dugout while {miss} "
        "waits to come on. {score}/100 at the half.",
        "The analysts are stunned: {stat}, yet {miss} is a no-show worth {miss_pts} points. That's a "
        "penalty miss in stoppage time.",
        "Instant replay confirms it: {stat}. The judges award {score}/100 and a long stare at the empty "
        "spot where {miss} should be.",
        "Clean sheet! {stat} and a {score}/100 finish; the judges will need video review to find a foul.",
    ],
    "movie trailer": [
        "They had {stat}. They had ambition. What they didn't have... was {miss}. PreJudge: {score}/100. "
        "Rated PG for Pretty Generous.",
        "From the studio that brought you {stat} comes the sequel nobody storyboarded: the search for "
        "{miss}. Opening at {score}/100.",
        "One demo. {video} of footage. A judging limit of 3:00. This fall, someone has to make the cut. "
        "{score}/100.",
        "Last seen on {date}. The commits stopped. The README went quiet. And somewhere out there, {miss} "
        "is still missing. {score}/100.",
        "Critics are calling it \"a repo with {stat}\". Critics are also asking where {miss} went. In "
        "theaters at {score}/100.",
        "This October, {stat} stand between one team and glory. Also standing in the way: {miss}, worth "
        "{miss_pts} points.",
        "In a season of half-finished repos, one team arrived with {stat} and {score}/100. The judges "
        "never saw it coming.",
    ],
    "food critic": [
        "The kitchen served {stat}, which is generous plating, but the main course, {miss}, never left "
        "the pass. {score}/100, and I'm still hungry.",
        "A {video} demo is not an appetiser, it's a nine-course tasting menu for a judge who booked a "
        "3:00 table. {score}/100.",
        "The ingredients were fresh on {date}; I'm less sure about them now. Missing from the plate: "
        "{miss}. {score}/100, would send back.",
        "{stat}: an ambitious menu. Then {miss} turned out to be \"off tonight\", which cost the table "
        "{miss_pts} points. {score}/100.",
        "I ordered {miss} and was brought {stat} instead. Inventive substitution. {score}/100, service "
        "not included.",
        "The house special is {stat}, served with a side of {score}/100. The sommelier suggests pairing "
        "it with {miss}.",
        "{stat}, plated with precision. {score}/100. I came to complain and left asking for the recipe.",
    ],
    "strict professor": [
        "You submitted {stat}. Impressive. The assignment asked for {miss}, which I note is absent. "
        "{score}/100; reread the rubric.",
        "Your demo runs {video}. The syllabus said 3:00. I stopped grading at 3:01. {score}/100.",
        "Last submission received {date}. The late-work policy also applies to {miss}, which I have yet "
        "to receive. {score}/100.",
        "Strong attendance: {stat}. Weak citations: {miss} is worth {miss_pts} points and appears nowhere "
        "in your bibliography. {score}/100.",
        "I counted {stat}. I also counted how many times you showed me {miss}: not once. {score}/100, "
        "resubmission encouraged.",
        "Grade: {score}/100. Commendable effort on {stat}; the remaining marks went to {miss}, which you "
        "forgot to hand in.",
        "{stat} and {score}/100. I have reread this submission twice looking for something to deduct.",
    ],
    "Bollywood drama": [
        "{stat}! Thunder strikes, the violins swell, and Maa asks the only question that matters: where "
        "is {miss}? {score}/100. Picture abhi baaki hai.",
        "Interval twist: the demo video runs {video}, longer than the item song. The judges walk out at "
        "3:00. {score}/100.",
        "Since {date} the repo has waited at the railway station for {miss}, which never arrives. "
        "Violins. {score}/100.",
        "The hero has {stat}. The villain has the rubric. And {miss}, worth {miss_pts} points, is lost "
        "at the mela. {score}/100.",
        "Dhishoom! {stat} land like a punch, but {miss} is still missing from the family photo. "
        "{score}/100, sequel pending.",
        "The family astrologer reads the stars: {stat}, a {score}/100 destiny, and {miss} returning in "
        "the final reel, hopefully before the deadline.",
        "{stat}, {score}/100, and not a single tear shed. Even the villain is clapping.",
    ],
}

MISSING = {
    "demo_video": "a demo video", "public_posts": "a single #neatHack post",
    "cfo_ai_plan": "a cfo.ai business plan", "neatlogs_sdk": "neatlogs tracing",
    "neatlogs_traces": "a neatlogs trace link", "entire_checkpoints": "an Entire checkpoint",
    "before_after": "a before/after comparison with numbers", "failure_recovery": "a documented failure run",
    "commits_in_window": "commits inside the hackathon window", "readme_exists": "a README worth reading",
    "dead_links": "links that work",
}


def _int(text: str | None, rx: str) -> int | None:
    m = re.search(rx, text or "")
    return int(m.group(1)) if m else None


def roast_slots(report: dict, score: dict) -> dict:
    """The facts a template may use, each phrased so it contains its fact-check anchor."""
    checks = {c["id"]: c for c in report.get("checks", [])}
    repo = report.get("repo") or {}
    slots: dict = {"score": score.get("score", 0)}

    stats = []  # (interest, phrase)
    commits = (checks.get("commits_in_window") or {})
    if commits.get("status") not in (None, "unverified"):
        inside = _int(commits["detail"], r"(\d+) inside")
        before = _int(commits["detail"], r"(\d+) before start")
        plus = "+" if "only latest" in commits["detail"] else ""
        if before and before >= 5:
            stats.append((90 + before, f"{before}{plus} commits pushed before the hackathon even started"))
        elif before and not inside:
            stats.append((70, f"{before} commit{'s' * (before > 1)}, all pushed before the hackathon even started"))
        if inside and inside >= 2:
            stats.append((20 + inside, f"{inside} commits inside the hackathon window"))
    m = re.search(r"(\d+)/(\d+) links dead", (checks.get("dead_links") or {}).get("detail", ""))
    if m and int(m.group(1)) >= 1:
        stats.append((80 + int(m.group(1)), f"{m.group(1)} of {m.group(2)} README links leading nowhere"))
    stars = repo.get("stars") or 0
    if stars >= 100:
        stats.append((60 + min(stars // 100, 100), f"{stars:,} GitHub stars"))
    words = _int((checks.get("readme_exists") or {}).get("detail"), r"(\d+) words")
    if words and words >= 1200:
        stats.append((35, f"{words} words of README"))
    files = report.get("files_seen") or 0
    if files >= 150:
        stats.append((30, f"{files} files"))
    if not stats and files:  # dull, so only when there is nothing better
        stats.append((0, f"{files} files"))
    if stats:
        slots["stat"] = max(stats)[1]

    video = (checks.get("demo_video") or {}).get("data") or {}
    if video.get("duration_status") == "too_long" and video.get("duration"):
        slots["video"] = video["duration"]
    pushed = repo.get("pushed_at")
    if pushed:
        from app.tools.rubric import WINDOW_START
        d = datetime.fromisoformat(pushed.replace("Z", "+00:00"))
        if d < WINDOW_START:
            slots["date"] = f"{d.day} {d:%b %Y}"

    for f in score.get("fix_candidates") or []:
        if f["check_id"] in MISSING:
            miss = MISSING[f["check_id"]]
            if f["check_id"] == "demo_video" and "video" in slots:
                miss = "a demo under 3:00"
            slots.update(miss=miss, miss_pts=f"{f['points']:g}")
            break
    return slots


COMPLIMENT_FROM = 80


def _fields(template: str) -> set[str]:
    return set(re.findall(r"{(\w+)}", template))


def _is_compliment(template: str) -> bool:
    return _fields(template) <= {"stat", "score"}


def template_roast(style: str, report: dict, score: dict, repo_name: str = "",
                   recent: list[str] | tuple = ()) -> str:
    """A fact-only roast in this repo's style, chosen by a hash of the repo name.

    Only templates whose slots all exist are eligible; the hash picks one, and the next one is
    tried if it would repeat a recent joke or break a roast rule.
    """
    slots = roast_slots(report, score)
    pool = TEMPLATES.get(style) or TEMPLATES["strict professor"]
    eligible = [t for t in pool if _fields(t) <= set(slots) and _fields(t) & {"stat", "date", "video"}]
    # Compliments ({stat} and {score} only) are for strong repos; everyone else gets roasted.
    strong = "miss" not in slots or slots["score"] >= COMPLIMENT_FROM
    eligible = [t for t in eligible if _is_compliment(t) == strong] or eligible
    if not eligible:
        facts = [f for f in build_facts(report) if f["anchors"] and not f["fact"].startswith("README claim")]
        return f"{facts[0]['fact'][:1].upper()}{facts[0]['fact'][1:]}, and {slots['score']}/100." if facts \
            else f"{slots['score']}/100: the judges will want more to go on."
    start = int(hashlib.sha256(f"{repo_name.lower()}|template".encode()).hexdigest(), 16) % len(eligible)
    facts = build_facts(report)
    first = None
    for i in range(len(eligible)):
        text = eligible[(start + i) % len(eligible)].format(**slots)
        first = first or text
        if not roast_problems(text, facts, list(recent), report):
            return text
    return first
