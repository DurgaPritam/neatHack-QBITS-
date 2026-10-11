"""Label sheets: one markdown file per repo that a human marks in about 2 minutes.

Each check (and each README claim) gets PreJudge's verdict, the evidence as direct GitHub
links, and a line to edit:

    label: ?            -> unlabelled
    label: ok           -> the verdict is right
    label: wrong        -> the verdict is wrong
    label: wrong pass   -> wrong, and the right verdict is `pass` (optional, helps re-runs)

A "wrong" on a `fail` is a false fail (we penalised something that is there): the worst kind.
"""
import re
from pathlib import Path

EVAL_CHECKS = {
    "commits_in_window": "Commits inside the hackathon window",
    "neatlogs_sdk": "neatlogs in the dependencies",
    "neatlogs_traces": "neatlogs trace links or screenshots",
    "entire_checkpoints": "Entire checkpoints",
    "cfo_ai_plan": "cfo.ai plan link",
    "demo_video": "Demo video link + length",
    "public_posts": "#neatHack posts",
    "before_after": "Before/after numbers",
    "failure_recovery": "Failure + recovery run",
}
STATUSES = ("pass", "warn", "fail", "unverified")
CLAIM_STATUSES = ("verified", "unverified", "contradicted")

_SECTION = re.compile(r"^## (check|claim) (\S+)", re.M)
_VERDICT = re.compile(r"^PreJudge: \*\*(\w+)\*\*", re.M)
_LABEL = re.compile(r"^label:\s*(\?|ok|wrong)(?:\s+(\w+))?\s*(?:--\s*(.*))?$", re.M)
_QUOTE = re.compile(r"^> (.*)$", re.M)


def _blob(repo: str, branch: str, ref: str) -> str | None:
    """Turn 'path/file.py:12' (or a bare path) into a GitHub link; None if it isn't a path."""
    m = re.match(r"^([\w./@+-]+\.[\w]+|[\w./-]+/[\w.-]+)(?::(\d+)(?:-(\d+))?)?$", ref.strip())
    if not m or ref.startswith(("http://", "https://")):
        return None
    path, a, b = m.groups()
    anchor = f"#L{a}" + (f"-L{b}" if b else "") if a else ""
    return f"https://github.com/{repo}/blob/{branch}/{path}{anchor}"


def _evidence_lines(repo: str, branch: str, check: dict) -> list[str]:
    out = []
    for ref in (check.get("evidence") or [])[:5]:
        ref = str(ref)
        if ref.startswith(("http://", "https://")):
            out.append(f"- <{ref}>")
        elif (link := _blob(repo, branch, ref)):
            out.append(f"- [{ref}]({link})")
        else:
            out.append(f"- `{ref[:160]}`")
    # a direct place to look, even when PreJudge found nothing
    where = {
        "commits_in_window": f"https://github.com/{repo}/commits/{branch}",
        "neatlogs_sdk": f"https://github.com/search?q=repo%3A{repo}+neatlogs&type=code",
        "entire_checkpoints": f"https://github.com/{repo}/commits/{branch}",
    }.get(check["id"], f"https://github.com/{repo}#readme")
    out.append(f"- look here: <{where}>")
    return out


def write_sheet(path: Path, entry: dict, url: str, report: dict, run_info: dict) -> None:
    repo = (report.get("repo") or {}).get("full_name") or url.split("github.com/")[-1].strip("/")
    branch = (report.get("repo") or {}).get("default_branch") or "HEAD"
    checks = {c["id"]: c for c in report.get("checks", [])}
    lines = [
        f"# {entry['name']}: eval label sheet",
        "",
        f"Repo: <{url}> · audit `{run_info.get('audit_id')}` · phase: {run_info.get('phase')} · "
        f"run {run_info.get('date')}",
        "",
        "Mark each `label:` line as `ok` or `wrong` (optionally `wrong pass` / `wrong fail` with the right "
        "verdict, and `-- a note`). A wrong **fail** is a false fail: we penalised something that is there.",
        "",
    ]
    for cid, title in EVAL_CHECKS.items():
        c = checks.get(cid)
        if not c:
            continue
        lines += [f"## check {cid}", f"**{title}**", "",
                  f"PreJudge: **{c['status']}** — {c['detail'][:300]}", ""]
        data = c.get("data") or {}
        if cid == "demo_video" and data.get("duration"):
            lines += [f"Length read: {data['duration']} (source: {data.get('duration_status')})", ""]
        lines += _evidence_lines(repo, branch, c) + ["", "label: ?", ""]
    for cl in (report.get("agent") or {}).get("claims", []):
        lines += [f"## claim {cl['claim_id']}", f"> {(cl.get('quote') or cl['claim'])[:240]}", "",
                  f"PreJudge: **{cl['status']}** — {cl.get('reason', '')[:240]}", ""]
        for e in (cl.get("evidence") or [])[:3]:
            ref = e.get("ref", "")
            link = ref if ref.startswith("http") else _blob(repo, branch, ref)
            lines.append(f"- [{ref}]({link})" if link else f"- `{ref[:120]}`")
        lines += ["", "label: ?", ""]
    path.write_text("\n".join(lines))


def parse_sheet(text: str) -> dict:
    """-> {"checks": {id: {verdict, label, truth, note}}, "claims": {id: {...}}}"""
    out: dict = {"checks": {}, "claims": {}}
    sections = list(_SECTION.finditer(text))
    for i, m in enumerate(sections):
        body = text[m.end():sections[i + 1].start() if i + 1 < len(sections) else len(text)]
        verdict = _VERDICT.search(body)
        label = _LABEL.search(body)
        if not verdict or not label:
            continue
        kind, key = m.groups()
        lab, truth, note = label.groups()
        quote = _QUOTE.search(body)
        out["checks" if kind == "check" else "claims"][key] = {
            "verdict": verdict.group(1), "label": None if lab == "?" else lab, "truth": truth,
            "note": (note or "").strip(), "quote": quote.group(1) if quote else None}
    return out


def truth_for(labelled: dict) -> str | None:
    """The right verdict, as far as the label tells us."""
    if labelled["label"] == "ok":
        return labelled["verdict"]
    if labelled["truth"]:
        return labelled["truth"]
    flip = {"fail": "pass", "pass": "fail", "verified": "contradicted", "contradicted": "verified"}
    return flip.get(labelled["verdict"])  # wrong on warn/unverified without a stated truth: unknown
