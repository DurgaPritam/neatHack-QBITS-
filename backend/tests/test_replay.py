"""LLM_MODE=replay / record. No network: GitHub is mocked, the LLM comes from fixtures."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from app import replay
from app.audit import run_full_audit
from app.llm import LLM, LLMError, QuotaPool
from app.steps import StepLog
from tests.test_agent import CLEAN_README, github


@pytest.fixture
def fixtures(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "FIXTURE_DIR", tmp_path)
    monkeypatch.setenv("LLM_MODE", "replay")
    fx = {"repo": "acme/demo", "source": "test",
          "responses": {
              "quick_verdict": {"roast": "6 commits inside the window and still no demo, a bold opening.",
                                "fixes": [], "best_thing": "It has a README."},
              "claims": {"claims": [{"id": "c1", "text": "uses neatlogs", "category": "tools"}],
                         "injection_attempts": []},
              "verify": {"results": [{"claim_id": "c1", "status": "verified",
                                      "evidence": [{"ref": "requirements.txt:1"}]}],
                         "estimates": {}, "injection_attempts": []},
              "verdict": {"roast": "6 commits in, neatlogs pinned in requirements.txt, demo still missing.",
                          "fixes": [], "best_thing": "Tracing is real."}},
          "verify_tool_calls": [{"name": "read_file", "arguments": {"path": "requirements.txt"}}],
          "usage": {"quick_verdict": 2000, "claims": 2500, "verify": 2500, "verdict": 2500}}
    (tmp_path / "acme__demo.json").write_text(json.dumps(fx))
    return tmp_path


def _audit(readme=CLEAN_README):
    log = StepLog()
    llm = LLM(log, models=["m"], pool=QuotaPool(["m"]), client=SimpleNamespace())  # client unused
    return asyncio.run(run_full_audit("https://github.com/acme/demo", run_kind="test", log=log, llm=llm,
                                      transport=github(readme), token=""))


def test_replay_runs_full_audit_without_network(fixtures):
    r = _audit()
    assert r["verdict"]["source"] == "llm"
    assert r["verdict"]["roast"].startswith("6 commits in, neatlogs pinned")
    assert [c["status"] for c in r["agent"]["claims"]] == ["verified"]  # evidence re-read and grounded
    llm_steps = [s for s in r["steps"] if s["name"].startswith("llm.")]
    assert llm_steps and all(s["data"]["model"] == "replay" for s in llm_steps)
    assert r["phases"]["quick"]["usage"]["total_tokens"] == 2000


def test_replayed_evidence_is_still_grounded(fixtures):
    fx = json.loads((fixtures / "acme__demo.json").read_text())
    fx["verify_tool_calls"] = []  # the cited file is never read in this replay
    (fixtures / "acme__demo.json").write_text(json.dumps(fx))
    r = _audit()
    assert r["agent"]["claims"][0]["status"] == "unverified"


def test_replay_miss_is_an_llm_outage(fixtures):
    log = StepLog()
    llm = LLM(log, models=["m"], pool=QuotaPool(["m"]), client=SimpleNamespace())
    with replay.repo_context("someone/else"), pytest.raises(LLMError) as e:
        asyncio.run(llm.chat("claims", [{"role": "user", "content": "x"}]))
    assert e.value.kind == "replay_miss" and log.steps[-1].error_kind == "replay_miss"


def test_record_mode_saves_first_response_per_purpose(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "FIXTURE_DIR", tmp_path)
    msg = SimpleNamespace(content='{"roast": "x y z"}', tool_calls=None)
    usage = SimpleNamespace(total_tokens=123)
    with replay.repo_context("Acme/Demo"):
        replay.record("verdict", msg, usage)
        replay.record("verdict.repair", SimpleNamespace(content='{"roast": "second"}', tool_calls=None), usage)
        call = SimpleNamespace(function=SimpleNamespace(name="search_repo", arguments='{"pattern": "a"}'))
        replay.record("verify", SimpleNamespace(content=None, tool_calls=[call]), usage)
    fx = json.loads((tmp_path / "acme__demo.json").read_text())
    assert fx["responses"]["verdict"] == {"roast": "x y z"} and fx["usage"]["verdict"] == 123
    assert fx["verify_tool_calls"] == [{"name": "search_repo", "arguments": {"pattern": "a"}}]


def test_shipped_fixtures_are_valid():
    from app.agent.schemas import ClaimList, Verdict, VerifyResult
    files = sorted(replay.FIXTURE_DIR.glob("*.json"))
    assert len(files) >= 3
    for f in files:
        fx = json.loads(f.read_text())
        r = fx["responses"]
        Verdict.model_validate(r["quick_verdict"])
        Verdict.model_validate(r["verdict"])
        ClaimList.model_validate(r["claims"])
        VerifyResult.model_validate(r["verify"])
        assert "org_01" not in f.read_text()
