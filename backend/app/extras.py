"""Demo script and judge panel: one LLM call each, grounded only in the audit's own facts.

Code owns the structure (scenes, times, personas) and every TODO: a scene whose tool has no
evidence in the audit is a TODO whatever the model writes, and any link the model makes up is
removed. The model only writes the words. No budget, a bad answer or a feature flag that's off
falls back to the template, which is built from the same facts.
"""
import json
import re

from pydantic import BaseModel, Field

from app import config
from app.agent.loop import ask_json
from app.agent.prompts import SECURITY_RULES, untrusted
from app.llm import BudgetExhausted, LLM, LLMError
from app.steps import StepLog

EXTRAS_VERSION = "2026-10-12.2"


def enabled(name: str) -> bool:
    """FEATURE_DEMO_SCRIPT / FEATURE_JUDGE_PANEL: on unless set to 0/false/off."""
    return config.env(f"FEATURE_{name.upper()}", "1").lower() not in ("0", "false", "off", "no")


# ---------------------------------------------------------------- facts

def _checks(report: dict) -> dict:
    return {c["id"]: c for c in report.get("checks", [])}


def _links(c: dict | None) -> list[str]:
    return [e for e in (c or {}).get("evidence") or [] if isinstance(e, str) and e.startswith("http")]


def facts(report: dict) -> dict:
    """Everything the LLM may use, as plain data. `have` says which demo topics have evidence."""
    c = _checks(report)
    ok = lambda cid: (c.get(cid) or {}).get("status") in ("pass", "warn")  # noqa: E731
    score = report.get("score") or {}
    entire = (c.get("entire_checkpoints") or {}).get("data") or {}
    video = (c.get("demo_video") or {}).get("data") or {}
    claims = (report.get("agent") or {}).get("claims") or []
    have = {
        "neatlogs": ok("neatlogs_sdk") or ok("neatlogs_traces"),
        "entire": (c.get("entire_checkpoints") or {}).get("status") in ("pass", "warn"),
        "cfo": ok("cfo_ai_plan"),
        "before_after": (c.get("before_after") or {}).get("status") == "pass",
        "failure": (c.get("failure_recovery") or {}).get("status") == "pass",
    }
    return {
        "repo": (report.get("repo") or {}).get("full_name") or report.get("repo_url"),
        "description": (report.get("repo") or {}).get("description") or "",
        "score": score.get("score"),
        "categories": {x["id"]: f"{x['points']}/{x['max_points']}" for x in score.get("categories", [])},
        "checks": {cid: {"status": x["status"], "detail": x.get("detail", "")[:160]} for cid, x in c.items()},
        "links": {"neatlogs_traces": _links(c.get("neatlogs_traces"))[:3], "cfo_ai": _links(c.get("cfo_ai_plan"))[:1],
                  "entire_checkpoint": [entire["checkpoint_link"]] if entire.get("checkpoint_link") else [],
                  "demo_video": _links(c.get("demo_video"))[:1], "posts": _links(c.get("public_posts"))[:3]},
        "entire_checkpoint_id": entire.get("checkpoint_id"),
        "video_length": video.get("duration"),
        "before_after": (c.get("before_after") or {}).get("evidence", [])[:2] if have["before_after"] else [],
        "verified_claims": [x["claim"][:140] for x in claims if x.get("status") == "verified"][:5],
        "top_fixes": [{"check": f["check_id"], "fix": f.get("fix") or f.get("title")}
                      for f in ((report.get("verdict") or {}).get("fixes") or [])[:4]],
        "have": have,
    }


def _allowed_urls(f: dict) -> set[str]:
    return {u for v in f["links"].values() for u in v} | {f"https://github.com/{f['repo']}"}


# full links, and bare ones like "docs.entire.io/guide" or "cfo.ai/s/abc"
_URL = re.compile(r"(?:https?://|\b(?=[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}/))[^\s)\]>\"'`]+", re.I)


def _bare(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url.rstrip(".,;:'\"")).rstrip("/").lower()


def _clean(text: str, f: dict, limit: int = 400) -> str:
    """Drop links the facts don't contain (with or without https://); trim."""
    allowed = {_bare(u) for u in _allowed_urls(f)}
    text = _URL.sub(lambda m: m.group(0) if _bare(m.group(0)) in allowed else "[link: TODO]", text or "")
    return " ".join(text.split())[:limit]


# ---------------------------------------------------------------- demo script

SCENES = [  # (id, start s, end s, topic, needs) — 3:00 in total, always
    ("hook", 0, 20, "The problem and the result in one line", None),
    ("architecture", 20, 50, "Architecture: how the agent is put together", None),
    ("neatlogs", 50, 85, "neatlogs: a real run's trace (runtime + the agent's reasoning, tool calls, a failure it recovered from)", "neatlogs"),
    ("entire", 85, 115, "Entire: how it was built (checkpoints of the implementation sessions)", "entire"),
    ("cfo", 115, 140, "cfo.ai: the business plan (pricing, costs, revenue, runway)", "cfo"),
    ("result", 140, 165, "Result: before/after numbers", "before_after"),
    ("close", 165, 180, "Close: where to try it", None),
]
TODO = {
    "neatlogs": "TODO: no neatlogs evidence found. Record a run with neatlogs tracing on and show its trace.",
    "entire": "TODO: no Entire checkpoint found. Push your checkpoints and show one (entire.io/gh/OWNER/REPO/commit/SHA).",
    "cfo": "TODO: no cfo.ai plan found. Build the plan in cfo.ai and show pricing, costs, revenue and runway.",
    "before_after": "TODO: no before/after numbers found. Run the agent before and after one improvement and show both numbers.",
}


def _mmss(s: int) -> str:
    return f"{s // 60}:{s % 60:02d}"


def _template_scene(sid: str, f: dict) -> tuple[str, str]:
    L = f["links"]
    name = (f["repo"] or "this repo").split("/")[-1]
    if sid == "hook":
        return (f"The app's home page, then the score ({f['score']}/100 on PreJudge).",
                f"{name}: {f['description'] or 'what it does, in one sentence'}.")
    if sid == "architecture":
        return ("A diagram or the repo tree: the agent, its tools and where tracing hooks in.",
                "Here's how the agent is put together: the loop, the tools it calls, and what it never does.")
    if sid == "neatlogs":
        trace = L["neatlogs_traces"][0] if L["neatlogs_traces"] else "the neatlogs dashboard"
        return (f"A trace in neatlogs ({trace}): the spans for each LLM and tool call, then a failed call and the retry.",
                "This is a real run in neatlogs: every model call, every tool call, and here's a failure the agent recovered from.")
    if sid == "entire":
        cp = L["entire_checkpoint"][0] if L["entire_checkpoint"] else "the Entire checkpoint"
        cid = f" (ID {f['entire_checkpoint_id']})" if f.get("entire_checkpoint_id") else ""
        return (f"The Entire checkpoint {cp}{cid}: the session that built a feature, linked to its commit.",
                "Entire recorded how this was built: each checkpoint ties an AI session to the commit it produced.")
    if sid == "cfo":
        plan = L["cfo_ai"][0] if L["cfo_ai"] else "the cfo.ai plan"
        return (f"The cfo.ai plan ({plan}): pricing, monthly costs, revenue and runway.",
                "The business side, modelled in cfo.ai: what it costs to run, what we charge, and how long the money lasts.")
    if sid == "result":
        ba = f["before_after"][0] if f["before_after"] else "the before/after table"
        return (f"The before/after numbers from the README: {ba}.",
                "One improvement, measured: here's the number before and after.")
    return (f"The repo (https://github.com/{f['repo']}) and the live link.",
            "Try it, read the code, and tell us what to fix next. #neatHack")


class _Scene(BaseModel):
    id: str
    show: str = Field(max_length=600)
    say: str = Field(max_length=600)


class _Script(BaseModel):
    scenes: list[_Scene]


DEMO_SYSTEM = f"""You write a 3-minute hackathon demo video script for a team, using ONLY the facts given.
{SECURITY_RULES}
Rules:
- Return JSON {{"scenes": [{{"id": "...", "show": "...", "say": "..."}}]}} with exactly the scene ids given, in order.
- "show" = what is on screen (concrete: which page, trace, checkpoint, plan). "say" = the voice-over,
  spoken in the first person plural, at most 2 short sentences (each scene is 15–35 seconds).
- Use only names, numbers and links that appear in the facts. Never invent a link, metric or feature.
- If a scene's evidence is missing, write "TODO:" and what the team must add, nothing else.
- Cover neatlogs (runtime + reasoning), Entire (implementation) and cfo.ai (business) explicitly."""


def _assemble(f: dict, written: dict[str, _Scene] | None, source: str) -> dict:
    scenes = []
    for sid, start, end, topic, needs in SCENES:
        missing = needs is not None and not f["have"].get(needs)
        show, say = _template_scene(sid, f)
        w = (written or {}).get(sid)
        if w and not missing:
            show, say = _clean(w.show, f) or show, _clean(w.say, f) or say
        if missing:  # code decides what's missing, not the model
            show, say = TODO[needs], "TODO"
        scenes.append({"id": sid, "start": _mmss(start), "end": _mmss(end), "seconds": end - start,
                       "topic": topic, "show": show, "say": say, "todo": missing or show.startswith("TODO")})
    text = "\n\n".join(f"[{s['start']}–{s['end']}] {s['topic']}\nSHOW: {s['show']}\nSAY: {s['say']}" for s in scenes)
    return {"version": EXTRAS_VERSION, "source": source, "total": _mmss(SCENES[-1][2]),
            "total_seconds": SCENES[-1][2], "scenes": scenes, "todos": sum(s["todo"] for s in scenes), "text": text}


async def demo_script(report: dict, llm: LLM | None) -> dict:
    f = facts(report)
    if llm is None:
        return _assemble(f, None, "template")
    wanted = [{"id": s[0], "topic": s[3], "evidence_present": s[4] is None or f["have"].get(s[4])} for s in SCENES]
    messages = [{"role": "system", "content": DEMO_SYSTEM},
                {"role": "user", "content": "Scenes:\n" + json.dumps(wanted) + "\n\nFacts:\n"
                 + untrusted("audit_facts", json.dumps({k: v for k, v in f.items() if k != "have"}, indent=1))}]
    try:
        out = await ask_json(llm, "demo_script", messages, _Script, max_tokens=1400)
    except (LLMError, BudgetExhausted):
        out = None
    if not out:
        return _assemble(f, None, "template")
    return _assemble(f, {s.id: s for s in out.scenes}, "llm")


# ---------------------------------------------------------------- judge panel

PERSONAS = [  # generic personas, never real judges
    ("observability", "Observability judge", ("neatlogs_traces", "neatlogs_sdk", "failure_recovery", "before_after")),
    ("dev_workflow", "Dev-workflow judge", ("entire_checkpoints", "commits_in_window", "public_posts", "readme_exists")),
    ("business", "Business judge", ("cfo_ai_plan", "demo_video")),
]
_PRAISE = {
    "neatlogs_traces": "Your neatlogs traces show real runs, not just a dependency.",
    "neatlogs_sdk": "neatlogs is wired into the code, so every run can be traced.",
    "failure_recovery": "You show a run that failed and how the agent recovered.",
    "before_after": "You measured an improvement with real before/after numbers.",
    "entire_checkpoints": "Your Entire checkpoints make the build history easy to follow.",
    "commits_in_window": "The commit history sits inside the hackathon window.",
    "public_posts": "You built in public with #neatHack posts.",
    "readme_exists": "The README gives judges a place to start.",
    "cfo_ai_plan": "There's a cfo.ai plan behind the product, not just a demo.",
    "demo_video": "The demo video is linked and within the time limit.",
}


class _Judge(BaseModel):
    id: str
    praise: str = Field(max_length=300)
    fix: str = Field(max_length=300)


class _Panel(BaseModel):
    judges: list[_Judge]


PANEL_SYSTEM = f"""You voice three generic hackathon judges (personas, not real people) reviewing one repo,
using ONLY the facts given.
{SECURITY_RULES}
Return JSON {{"judges": [{{"id": "...", "praise": "...", "fix": "..."}}]}} for the ids given, in order.
- praise: ONE sentence about something that passed in that judge's area, citing a specific fact.
- fix: ONE sentence: the single most valuable specific fix in that area (from the failing/warn checks).
  If everything in the area passed, suggest how to make the strongest piece of evidence easier for judges to find.
- Never name or impersonate real people. Never invent links, numbers or features."""


def _template_judge(pid: str, title: str, area: tuple, f: dict) -> dict:
    checks = f["checks"]
    good = [cid for cid in area if checks.get(cid, {}).get("status") == "pass"]
    bad = [cid for cid in area if checks.get(cid, {}).get("status") in ("fail", "warn")]
    praise = _PRAISE[good[0]] if good else "There's a clear starting point here to build evidence on."
    fix = next((x["fix"] for x in f["top_fixes"] if x["check"] in bad), None) if bad else None
    if not fix and bad:
        fix = f"Fix this first: {checks[bad[0]]['detail']}."
    return {"id": pid, "title": title, "praise": praise,
            "fix": fix or "Everything here passed; link the strongest evidence near the top of the README."}


async def judge_panel(report: dict, llm: LLM | None) -> dict:
    f = facts(report)
    base = [_template_judge(pid, title, area, f) for pid, title, area in PERSONAS]
    source, written = "template", {}
    if llm is not None:
        wanted = [{"id": pid, "title": title, "area_checks": {cid: f["checks"].get(cid) for cid in area}}
                  for pid, title, area in PERSONAS]
        messages = [{"role": "system", "content": PANEL_SYSTEM},
                    {"role": "user", "content": "Judges:\n" + json.dumps(wanted) + "\n\nFacts:\n"
                     + untrusted("audit_facts", json.dumps({k: v for k, v in f.items() if k != "have"}, indent=1))}]
        try:
            out = await ask_json(llm, "judge_panel", messages, _Panel, max_tokens=700)
        except (LLMError, BudgetExhausted):
            out = None
        if out:
            written = {j.id: j for j in out.judges}
            source = "llm"
    judges = []
    for b in base:
        w = written.get(b["id"])
        judges.append({**b, **({"praise": _clean(w.praise, f, 240) or b["praise"],
                                "fix": _clean(w.fix, f, 240) or b["fix"]} if w else {})})
    return {"version": EXTRAS_VERSION, "source": source if written else "template", "judges": judges}


def new_llm(steps: StepLog | None = None) -> LLM:
    return LLM(steps or StepLog(), priority="high")
