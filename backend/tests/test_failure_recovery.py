"""Failure + recovery: the quick phase never costs points; the deep phase verifies like a claim."""
from app.scoring import compute_score
from app.tools.rubric import check_failure_run, verify_failure_recovery

RUN = ("During the deep check of audit `29def6e19f64`, `llm.verify` failed with a Groq 429.\n"
       "The agent backed off and retried on the fallback model, then finished the audit.\n")
RETRY_CODE = "import httpx\n\nasync def call_with_retry(fn):\n    for attempt in range(3):\n        pass\n"


def verify(readme="# Demo\n", files=None, tree=None, claims=None):
    files = {} if files is None else files
    return verify_failure_recovery(readme, "README.md", files, tree or list(files), claims)


# ------------------------------------------------------------------ quick phase

def test_quick_phase_does_not_score_a_mentioned_failure_run():
    c = check_failure_run("# X\n\nOn a 429 the agent retries on a fallback model.\n")
    assert c["status"] == "unverified" and c["data"]["not_scored"] and c["data"]["pending"] == "deep"


def test_quick_phase_does_not_score_when_evidence_docs_exist():
    c = check_failure_run("# X\n", ["EVIDENCE.md", "app/main.py"])
    assert c["data"]["not_scored"] and "EVIDENCE.md" in c["evidence"]


def test_quick_phase_fails_only_when_there_is_nothing_to_check():
    c = check_failure_run("# X\n", ["README.md", "main.py"])
    assert c["status"] == "fail" and not (c.get("data") or {}).get("not_scored")


def test_quick_score_does_not_drop_for_unchecked_failure_run():
    base = [{"id": "before_after", "title": "b", "status": "pass", "detail": ""}]
    pending = base + [check_failure_run("On a 429 we retry on a fallback model.")]
    failed = base + [check_failure_run("# nothing\n", ["main.py"])]
    assert compute_score(pending)["score"] > compute_score(failed)["score"]
    agent = next(c for c in compute_score(pending)["categories"] if c["id"] == "agent")
    row = next(r for r in agent["items"] if r["id"] == "failure_recovery")
    assert row["not_scored"] and row["max_points"] == 0


# ------------------------------------------------------------------ deep phase

def test_described_run_with_trace_link_passes():
    doc = RUN + "Trace: https://app.neatlogs.com/traces/abc123?orgId=1\n"
    c = verify(files={"EVIDENCE.md": doc})
    assert c["status"] == "pass"
    assert c["data"]["described"][0]["ref"] == "EVIDENCE.md:1"
    assert any(e["kind"] == "trace link" for e in c["data"]["backing"])


def test_screenshot_must_exist_in_the_repo():
    doc = RUN + "![trace](evidence/fail.png)\n"
    c = verify(files={"docs/run.md": doc}, tree=["docs/run.md"])
    assert c["status"] == "warn"  # image link points at a file that isn't there
    c = verify(files={"docs/run.md": doc}, tree=["docs/run.md", "docs/evidence/fail.png"])
    assert c["status"] == "pass" and c["data"]["backing"][0] == {"kind": "screenshot", "ref": "docs/evidence/fail.png"}


def test_readme_description_backed_by_retry_code_passes():
    c = verify(readme="# Demo\n\n" + RUN, files={"app/llm.py": RETRY_CODE})
    assert c["status"] == "pass"
    assert {"kind": "retry/fallback code", "ref": "app/llm.py:3"} in c["data"]["backing"]


def test_readme_alone_is_not_proof():
    c = verify(readme="# Demo\n\n" + RUN, files={"app/main.py": "print('hi')\n"})
    assert c["status"] == "warn" and "no trace link" in c["detail"]
    assert c["data"]["advice"]


def test_code_without_a_described_run_is_partial():
    c = verify(files={"agent/loop.py": RETRY_CODE})
    assert c["status"] == "warn" and "no run is described" in c["detail"]


def test_log_file_counts_as_evidence():
    log = "ERROR 429 rate limited on model a\nINFO retrying with fallback model b\n"
    c = verify(readme="# Demo\n\n" + RUN, files={"logs/run-1.log": log})
    assert c["status"] == "pass" and {"kind": "log", "ref": "logs/run-1.log"} in c["data"]["backing"]


def test_verified_claim_about_recovery_counts():
    claims = [{"claim_id": "c3", "claim": "On a 429 the agent retries on the fallback model",
               "status": "verified"}]
    c = verify(readme="# Demo\n\n" + RUN, files={"main.py": "x = 1\n"}, claims=claims)
    assert c["status"] == "pass" and c["data"]["backing"][0]["kind"] == "verified claim"


def test_vague_sentence_is_not_a_described_run():
    c = verify(readme="# Demo\n\nThe agent retries on failure.\n", files={"main.py": "x = 1\n"})
    assert c["status"] == "fail"


def test_tests_do_not_count_as_retry_code():
    c = verify(files={"tests/test_retry.py": RETRY_CODE})
    assert c["status"] == "fail"


def test_no_tarball_is_not_scored():
    c = verify_failure_recovery(RUN, "README.md", None, [])
    assert c["status"] == "unverified" and c["data"]["not_scored"]
