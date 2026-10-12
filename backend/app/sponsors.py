"""Sponsor Depth Scorecard: how deeply a repo uses neatlogs, Entire and cfo.ai, from 1 to 4.

1 mentioned · 2 installed/linked · 3 evidence shown · 4 used to improve the project.
Every level comes from the existing checks (no LLM). Levels are cumulative and conservative:
when the evidence for the next level isn't certain, the tool gets the lower level and the reason.
0 means not even mentioned.
"""
import re

LEVELS = {0: "not found", 1: "mentioned", 2: "installed / linked", 3: "evidence shown", 4: "used to improve"}

_NEAT = re.compile(r"neatlogs|trace|token|latency|cost|ms\b|tok\b", re.I)
_ENTIRE = re.compile(r"\bentire\b|checkpoint", re.I)
_CFO = re.compile(r"cfo\.ai|cfo ai|\bari\b|pricing|runway|break-?even|margin", re.I)


def _c(report: dict) -> dict:
    return {c["id"]: c for c in report.get("checks", [])}


# a level-4 claim must say something changed, not just that the tool is used
_CHANGED = re.compile(r"\b(chang\w*|switch\w*|replac\w*|mov\w*|improv\w*|reduc\w*|cut|rais\w*|lower\w*|revert\w*|"
                      r"instead|before|after|earlier|later|decid\w*|decision)\b", re.I)


def _verified_claims(report: dict, rx: re.Pattern) -> list[str]:
    claims = (report.get("agent") or {}).get("claims") or []
    return [c["claim"] for c in claims if c.get("status") == "verified" and rx.search(c.get("claim", ""))
            and _CHANGED.search(c.get("claim", ""))]


def _row(tool: str, level: int, why: str, next_step: str, evidence: list[str]) -> dict:
    return {"tool": tool, "level": level, "label": LEVELS[level], "why": why, "next_step": next_step,
            "evidence": [e for e in evidence if e][:3]}


def neatlogs(report: dict) -> dict:
    c = _c(report)
    sdk, traces = c.get("neatlogs_sdk") or {}, c.get("neatlogs_traces") or {}
    ba, fr = c.get("before_after") or {}, c.get("failure_recovery") or {}
    if sdk.get("status") != "pass":
        if sdk.get("status") == "warn" or traces.get("status") in ("pass", "warn"):
            return _row("neatlogs", 1, "neatlogs is mentioned, but no dependency file declares it",
                        "Add the neatlogs SDK to your dependencies and initialise it where the agent starts.",
                        sdk.get("evidence", []))
        return _row("neatlogs", 0, "no sign of neatlogs in the dependencies or README",
                    "pip install neatlogs, call neatlogs.init() at startup and trace each agent run.", [])
    if traces.get("status") != "pass":
        why = ("neatlogs is a dependency, but its trace links need a login to view"
               if traces.get("status") == "warn" else "neatlogs is a dependency, but no traces are shown")
        return _row("neatlogs", 2, why,
                    "Add 1–3 trace screenshots to the README (or public share links) of real runs.",
                    sdk.get("evidence", []))
    snippets = [s for s in ba.get("evidence", []) if _NEAT.search(str(s))] if ba.get("status") == "pass" else []
    if snippets:
        return _row("neatlogs", 4, "traces are shown and the README compares runs before/after with numbers",
                    "Link the before and after traces next to the numbers so judges can open both runs.",
                    [*snippets[:2], *traces.get("evidence", [])[:1]])
    why = "traces are shown, but no before/after numbers tie them to an improvement"
    if fr.get("status") == "pass":
        why += " (a failure + recovery run is documented)"
    return _row("neatlogs", 3, why,
                "Use the traces to change one thing (prompt, model, tool) and publish before/after numbers.",
                traces.get("evidence", []))


def entire(report: dict) -> dict:
    c = (_c(report).get("entire_checkpoints") or {})
    data, status, detail = c.get("data") or {}, c.get("status"), c.get("detail", "")
    if status not in ("pass", "warn"):
        hints = c.get("evidence", [])
        if hints:
            return _row("Entire", 1, "Entire is mentioned or configured, but no checkpoints were found in git",
                        "Run `entire enable`, work through it, and push the checkpoint refs with your commits.", hints)
        return _row("Entire", 0, "no Entire checkpoints, config or mention found",
                    "Install Entire (`entire enable`) so each AI session is checkpointed with its commit.", [])
    link = data.get("checkpoint_link")
    if status == "warn":
        return _row("Entire", 2, "checkpoints are in git, but the README doesn't link one judges can open"
                    + (" (the link is dead)" if "dead" in detail else ""),
                    f"Link a checkpoint and its ID in the README{': ' + link if link else ''}.",
                    [link] if link else c.get("evidence", []))
    claims = _verified_claims(report, _ENTIRE)
    if claims:
        return _row("Entire", 4, "checkpoints are linked and a verified README claim ties them to how the project changed",
                    "Point to the checkpoint where you changed course and say what changed.", [link, *claims[:1]])
    return _row("Entire", 3, "real checkpoints are linked with their IDs; nothing verified shows them changing a decision",
                "Write one line per key checkpoint: what you tried, what changed after it.",
                [link] if link else c.get("evidence", []))


def cfo(report: dict) -> dict:
    c = (_c(report).get("cfo_ai_plan") or {})
    status, detail, links = c.get("status"), c.get("detail", ""), [e for e in c.get("evidence", []) if str(e).startswith("http")]
    topics = (c.get("data") or {}).get("topics") or []
    if "dead" in detail:
        return _row("cfo.ai", 1, "the cfo.ai plan link is dead",
                    "Re-share the plan from cfo.ai and replace the link in the README.", links)
    if not links:
        if status == "warn":
            return _row("cfo.ai", 1, "cfo.ai is mentioned, but no plan is linked",
                        "Build the plan with Ari in cfo.ai, share it and link it in the README.", [])
        return _row("cfo.ai", 0, "no cfo.ai plan found",
                    "Build the plan with Ari in cfo.ai (pricing, costs, revenue, runway) and link it.", [])
    if status != "pass":
        missing = [t for t in ("pricing", "cost", "revenue", "runway") if t not in topics]
        return _row("cfo.ai", 2, f"plan linked; the README doesn't cover {', '.join(missing) or 'enough of the plan'}",
                    "Summarise pricing, costs, revenue and runway from the plan in the README.", links)
    claims = _verified_claims(report, _CFO)
    if claims:
        return _row("cfo.ai", 4, "plan linked and summarised, and a verified claim shows it changed a number or decision",
                    "Show the plan version before and after that decision, side by side.", [*links[:1], claims[0]])
    return _row("cfo.ai", 3, "plan linked and the README covers its pricing, costs, revenue and runway",
                "Feed real measured numbers (cost per run, usage) into the plan and note what changed.", links)


def _signal(report: dict, sid: str) -> dict | None:
    return next((s for s in (report.get("integrity") or {}).get("signals", []) if s["id"] == sid), None)


def _cap(row: dict, level: int, why: str, next_step: str) -> dict:
    """An integrity signal that needs a look caps the level: that evidence can't count until it's cleared."""
    if row["level"] <= level:
        return row
    return {**row, "level": level, "label": LEVELS[level], "why": why, "next_step": next_step, "capped_by_integrity": True}


def scorecard(report: dict) -> list[dict]:
    n, e, c = neatlogs(report), entire(report), cfo(report)
    links = _signal(report, "links_this_repo")
    foreign = [u for u in (links or {}).get("evidence", []) if "entire.io" in u] if (links or {}).get("status") == "look" else []
    link = ((next((x for x in report.get("checks", []) if x["id"] == "entire_checkpoints"), {}) or {}).get("data") or {}).get("checkpoint_link")
    if foreign and (link in foreign or not link):
        e = _cap(e, 2, "the README's Entire link points to a different repo (see Integrity checks), so it can't count",
                 "Link a checkpoint from this repo: entire.io/gh/OWNER/REPO/commit/SHA.")
    cps = _signal(report, "checkpoints_real")
    if (cps or {}).get("status") == "look":
        e = _cap(e, 2, "a quoted checkpoint ID needs a look (see Integrity checks): " + cps["reason"][:120],
                 "Quote checkpoint IDs that exist in this repo's pushed refs.")
    shots = _signal(report, "screenshots")
    if (shots or {}).get("status") == "look" and n["level"] >= 3:
        n = _cap(n, 2, "the trace screenshots need a look (see Integrity checks): " + shots["reason"][:120],
                 "Use a real, full-size screenshot of each trace (one file per run).")
    return [n, e, c]
