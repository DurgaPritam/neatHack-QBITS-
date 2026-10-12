# PreJudge MCP server

Audit a hackathon repo against the neatHack rubric from Claude Code, Cursor or any MCP client.
It's a thin stdio wrapper around PreJudge's public API (`https://3-82-224-157.sslip.io`): nothing
runs locally except this file, and PreJudge never runs your code either.

| Tool | What it does |
|---|---|
| `audit_repo(repo_url)` | Quick audit (~15s): score 0–100, roast, top 3 fixes, checks that didn't pass, `audit_id` |
| `deep_check(audit_id, wait=true)` | Reads the code and verifies every README claim, then rescores (up to ~7 min) |
| `get_result(audit_id)` | Current result: score, quick/deep, fixes, progress since the last check |
| `next_fix(audit_id)` | The single fix worth the most points, and the two after it |

## Install

```bash
git clone https://github.com/DurgaPritam/neatHack-QBITS-.git && cd neatHack-QBITS-/mcp
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

### Claude Code

```bash
claude mcp add prejudge -- "$PWD/.venv/bin/python" "$PWD/prejudge_mcp.py"
```

Then ask: *"Audit https://github.com/you/your-repo with prejudge and tell me the next fix."*

### Cursor

Add to `~/.cursor/mcp.json` (or `.cursor/mcp.json` in a project), with absolute paths:

```json
{
  "mcpServers": {
    "prejudge": {
      "command": "/absolute/path/to/neatHack-QBITS-/mcp/.venv/bin/python",
      "args": ["/absolute/path/to/neatHack-QBITS-/mcp/prejudge_mcp.py"]
    }
  }
}
```

## Rate limits

The public API allows 5 new audits per 10 minutes per IP and a few deep checks per hour; deep
checks also share a daily AI budget. The server spaces new audits at least 20s apart, polls every
3s, and on HTTP 429 returns the API's message with the retry time instead of retrying.
Re-auditing an unchanged commit returns the saved result (no budget spent).

Set `PREJUDGE_API` to point at another PreJudge deployment (e.g. `http://localhost:8000`).

## Tests

```bash
.venv/bin/python -m pytest -q                       # offline
PREJUDGE_E2E=1 .venv/bin/python -m pytest -q -s     # end to end over stdio against the live API
```
