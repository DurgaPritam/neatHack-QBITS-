"""Copy-paste helpers built from an audit: the submission post, the Evidence section and the README badge.

Everything here only reuses what the checks found. Anything missing becomes a clearly marked blank
(`[___]` in the post, `TODO:` in the Evidence section): we never invent a link or a number.
"""
import re
from html import escape

X_LIMIT = 280
X_URL_LEN = 23          # X counts every link as 23 characters (t.co)
_URL = re.compile(r"https?://\S+")
BLANK = "[___]"


def x_length(text: str) -> int:
    return len(_URL.sub("x" * X_URL_LEN, text))


def _checks(report: dict) -> dict:
    return {c["id"]: c for c in report.get("checks", [])}


def _urls(check: dict | None) -> list[str]:
    return [e for e in (check or {}).get("evidence") or [] if isinstance(e, str) and e.startswith("http")]


def _good(check: dict | None) -> bool:
    return bool(check) and check["status"] in ("pass", "warn")


def demo_url(report: dict) -> str | None:
    c = _checks(report).get("demo_video") or {}
    if (c.get("data") or {}).get("duration_status") in ("no_video", "dead_link", "unwatchable"):
        return None
    urls = _urls(c)
    return urls[0] if urls else None


def submission_post(report: dict) -> dict:
    """The official format: Team, Name, Project, Repo, Demo, #neatHack. Blanks for what we don't know."""
    repo = report.get("repo") or {}
    full = repo.get("full_name") or report.get("repo_url", "").split("github.com/")[-1]
    name = full.split("/")[-1] if full else BLANK
    url = f"https://github.com/{full}" if full else BLANK
    lines = [f"Team: {BLANK}", f"Name: {BLANK}", f"Project: {name}", f"Repo: {url}",
             f"Demo: {demo_url(report) or BLANK}", "#neatHack"]
    desc = " ".join((repo.get("description") or "").split())
    if desc:   # one line about the project, only while the post still fits
        base = x_length("\n".join(lines))
        room = X_LIMIT - base - 3
        if room >= 20:
            short = desc if len(desc) <= room else desc[:room - 1].rsplit(" ", 1)[0] + "…"
            lines[2] = f"Project: {name} — {short}"
    text = "\n".join(lines)
    n = x_length(text)
    return {"text": text, "length": n, "limit": X_LIMIT, "over": n > X_LIMIT,
            "blanks": text.count(BLANK)}


def evidence_markdown(report: dict, result_url: str) -> str:
    """A README 'Evidence' section from what PreJudge found, with TODOs where judges will look for more."""
    c = _checks(report)
    out = ["## Evidence", "", f"_Checked by [PreJudge]({result_url})._", ""]

    def item(title: str, found: list[str], todo: str) -> None:
        if found:
            out.append(f"- **{title}:** " + " · ".join(found))
        else:
            out.append(f"- **{title}:** ⚠️ TODO: {todo}")

    sdk = c.get("neatlogs_sdk")
    item("neatlogs in the code", [f"`{e}`" for e in (sdk or {}).get("evidence", [])[:2] if not str(e).startswith("http")]
         if _good(sdk) else [], "add the neatlogs SDK to your dependencies and trace each agent run")
    traces = _urls(c.get("neatlogs_traces")) if _good(c.get("neatlogs_traces")) else []
    item("neatlogs traces", [f"[trace {i + 1}]({u})" for i, u in enumerate(traces[:3])],
         "link 1–3 neatlogs traces (or screenshots) of real runs")
    e = (c.get("entire_checkpoints") or {}).get("data") or {}
    item("Entire checkpoint", [f"[{e.get('checkpoint_id') or 'checkpoint'}]({e['checkpoint_link']})"] if e.get("checkpoint_link")
         else [], "link an Entire checkpoint (https://entire.io/gh/OWNER/REPO/commit/SHA) and its ID")
    cfo = _urls(c.get("cfo_ai_plan")) if _good(c.get("cfo_ai_plan")) else []
    item("cfo.ai business plan", [f"[plan]({u})" for u in cfo[:1]],
         "link your cfo.ai plan (pricing, costs, revenue, runway)")
    v = c.get("demo_video") or {}
    vd = v.get("data") or {}
    url = demo_url(report)
    length = f" ({vd['duration']})" if vd.get("duration") else ""
    warn = " ⚠️ over 3 minutes: trim it" if vd.get("duration_status") == "too_long" else ""
    item("Demo video", [f"[demo]({url}){length}{warn}"] if url else [],
         "link a demo video, 3 minutes or less, that shows neatlogs, Entire and cfo.ai")
    ba = c.get("before_after")
    item("Before/after", [f"“{s[:120]}”" for s in (ba or {}).get("evidence", [])[:2]] if (ba or {}).get("status") == "pass"
         else [], "a before/after table with numbers (accuracy, tokens, time) from two runs")
    fr = c.get("failure_recovery")
    item("Failure + recovery", [f"`{x}`" if not str(x).startswith("http") else f"[run]({x})"
                                for x in (fr or {}).get("evidence", [])[:2]] if (fr or {}).get("status") == "pass" else [],
         "describe one run where a call failed and what the agent did next, with a trace link")
    posts = _urls(c.get("public_posts")) if _good(c.get("public_posts")) else []
    item("#neatHack posts", [f"[post {i + 1}]({u})" for i, u in enumerate(posts[:4])],
         "link your building-in-public posts tagged #neatHack")
    return "\n".join(out) + "\n"


def _tone(score: int | None) -> str:
    if score is None:
        return "#9f9f9f"
    return "#2fb344" if score >= 70 else "#e8a317" if score >= 40 else "#e5533d"  # labels.ts scoreTone


def badge_svg(score: int | None) -> str:
    """A shields-style badge: 'PreJudge | 73/100'."""
    left, right = "PreJudge", "not roasted" if score is None else f"{score}/100"
    lw, rw = 62, 12 + 7 * len(right)
    w = lw + rw
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="20" role="img" aria-label="{left}: {escape(right)}">
<title>{left}: {escape(right)}</title>
<linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>
<clipPath id="r"><rect width="{w}" height="20" rx="3" fill="#fff"/></clipPath>
<g clip-path="url(#r)"><rect width="{lw}" height="20" fill="#2b2b33"/><rect x="{lw}" width="{rw}" height="20" fill="{_tone(score)}"/><rect width="{w}" height="20" fill="url(#s)"/></g>
<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
<text x="{lw / 2}" y="14">{left}</text><text x="{lw + rw / 2}" y="14">{escape(right)}</text></g>
</svg>"""
