"""Eval label sheets: written, marked by a human, parsed back and scored."""
from evals import labels as L
from evals import run as R

REPORT = {
    "repo": {"full_name": "team/app", "default_branch": "main"},
    "checks": [
        {"id": "commits_in_window", "status": "pass", "detail": "12 inside", "evidence": []},
        {"id": "cfo_ai_plan", "status": "fail", "detail": "no cfo.ai link", "evidence": []},
        {"id": "neatlogs_sdk", "status": "pass", "detail": "in requirements.txt", "evidence": ["requirements.txt:3"]},
        {"id": "demo_video", "status": "fail", "detail": "video is 4:10", "evidence": ["https://youtu.be/x"],
         "data": {"duration": "4:10", "duration_status": "too_long"}},
    ],
    "agent": {"claims": [{"claim_id": "c1", "claim": "uses neatlogs", "quote": "We trace with neatlogs",
                          "status": "verified", "evidence": [{"ref": "app/tracing.py:12"}], "reason": "found"}]},
}


def sheet(tmp_path, edits: dict[str, str]):
    p = tmp_path / "repo-x.md"
    L.write_sheet(p, {"name": "Repo X"}, "https://github.com/team/app", REPORT,
                  {"audit_id": "abc", "phase": "deep", "date": "2026-10-11"})
    text = p.read_text()
    for section, label in edits.items():
        head = text.index(f"## {section}")
        at = text.index("label: ?", head)
        text = text[:at] + f"label: {label}" + text[at + len("label: ?"):]
    p.write_text(text)
    return p


def test_sheet_has_verdicts_and_direct_links(tmp_path):
    text = sheet(tmp_path, {}).read_text()
    assert "PreJudge: **fail** — no cfo.ai link" in text
    assert "[requirements.txt:3](https://github.com/team/app/blob/main/requirements.txt#L3)" in text
    assert "<https://github.com/team/app/commits/main>" in text and "Length read: 4:10" in text
    assert "[app/tracing.py:12](https://github.com/team/app/blob/main/app/tracing.py#L12)" in text
    assert text.count("label: ?") == 5


def test_parse_and_truth(tmp_path):
    p = sheet(tmp_path, {"check cfo_ai_plan": "wrong -- plan linked in docs/plan.md",
                         "check neatlogs_sdk": "ok", "check demo_video": "wrong pass", "claim c1": "ok"})
    parsed = L.parse_sheet(p.read_text())
    cfo = parsed["checks"]["cfo_ai_plan"]
    assert cfo == {"verdict": "fail", "label": "wrong", "truth": None, "note": "plan linked in docs/plan.md",
                   "quote": None}
    assert L.truth_for(cfo) == "pass"                       # a wrong fail means it's there
    assert L.truth_for(parsed["checks"]["demo_video"]) == "pass"
    assert parsed["checks"]["commits_in_window"]["label"] is None
    assert parsed["claims"]["c1"]["quote"] == "We trace with neatlogs"


def test_score_counts_false_fails_and_claim_agreement(tmp_path, monkeypatch):
    labels_dir = tmp_path / "labels"
    labels_dir.mkdir()
    p = sheet(tmp_path, {"check cfo_ai_plan": "wrong", "check neatlogs_sdk": "ok", "claim c1": "ok"})
    (labels_dir / "repo-x.md").write_text(p.read_text())
    monkeypatch.setattr(R, "HERE", tmp_path)
    run = {"id": "repo-x", "audit_id": "abc", "phase": "deep", "report": REPORT, "tokens": 100, "seconds": 1}
    s = R.score_run([run])
    assert s["overall"]["false_fails"] == 1 and s["overall"]["accuracy"] == 50.0
    assert s["top_errors"] == [{"check": "cfo_ai_plan", "kind": "false_fail", "count": 1}]
    assert s["claims"]["agreement"] == 100.0
    # after a fix the check passes: the same label now scores it correct
    fixed = {**REPORT, "checks": [{**c, "status": "pass"} if c["id"] == "cfo_ai_plan" else c for c in REPORT["checks"]]}
    s2 = R.score_run([{**run, "report": fixed}])
    assert s2["overall"]["false_fails"] == 0 and s2["overall"]["accuracy"] == 100.0


def test_committed_files_never_name_other_teams():
    import yaml
    repos = yaml.safe_load((R.HERE / "repos.yaml").read_text())["repos"]
    for e in repos:
        if e["kind"] == "neathack":
            assert "url" not in e and e["name"].startswith("Repo ")
    ignore = (R.HERE / ".gitignore").read_text()
    assert "repos.private.yaml" in ignore and "private/" in ignore and "labels/repo-*.md" in ignore
