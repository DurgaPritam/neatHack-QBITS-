"""The copy-paste GitHub Action (docs/prejudge.yml): run its exact bash step against a stub API."""
import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / "docs" / "prejudge.yml"
ACTIVE = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "prejudge.yml"
AUDIT = {"id": "abc123def456", "status": "complete", "result": {
    "score": {"score": 61, "categories": [{"id": "demo_video", "points": 0, "max_points": 20}]},
    "progress": {"text": "+7 since your last check (54 → 61)"},
    "verdict": {"roast": "ouch", "fixes": [{"title": "Demo video", "points": 20.0, "fix": "Record it."}]}}}


def _serve(post_status: int):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if post_status == 429:
                return self._send(429, {"detail": "Easy there: 5 new audits per 10 minutes per person."})
            self._send(200, {"id": "abc123def456", "status": "queued"})

        def do_GET(self):
            self._send(200, AUDIT)
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _run(tmp_path, api, min_score="0"):
    script = yaml.safe_load(WORKFLOW.read_text())["jobs"]["prejudge"]["steps"][0]["run"]
    summary = tmp_path / "summary.md"
    env = {**os.environ, "PREJUDGE_API": api, "MIN_SCORE": min_score, "GITHUB_REPOSITORY": "team/app",
           "GITHUB_SHA": "0123456789abcdef", "GITHUB_STEP_SUMMARY": str(summary)}
    p = subprocess.run(["bash", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    return p.returncode, summary.read_text() if summary.exists() else ""


needs_jq = pytest.mark.skipif(not shutil.which("jq"), reason="jq not installed")


@needs_jq
def test_summary_has_score_progress_and_fixes(tmp_path):
    srv = _serve(200)
    code, md = _run(tmp_path, f"http://127.0.0.1:{srv.server_port}")
    assert code == 0 and "## 🔥 PreJudge: 61/100" in md and "Deep check of 0123456" in md
    assert "+7 since your last check" in md and "| demo_video | 0 / 20 |" in md
    assert "1. **Demo video** (+20.0 pts): Record it." in md
    assert _run(tmp_path, f"http://127.0.0.1:{srv.server_port}", min_score="70")[0] == 1   # opt-in gate
    srv.shutdown()


@needs_jq
def test_rate_limit_and_outage_never_fail_the_build(tmp_path):
    srv = _serve(429)
    code, md = _run(tmp_path, f"http://127.0.0.1:{srv.server_port}")
    assert code == 0 and "HTTP 429" in md and "5 new audits per 10 minutes" in md
    srv.shutdown()
    code, md = _run(tmp_path, "http://127.0.0.1:9")
    assert code == 0 and "couldn't start an audit" in md


def test_active_workflow_is_the_documented_one():
    if ACTIVE.exists():
        assert ACTIVE.read_text() == WORKFLOW.read_text()
