# PreJudge: get roasted before the judges do

**Live: https://3-82-224-157.sslip.io** · neatHack (Oct 10–12, 2026) · team QBITS (Durga Pritam Suggisetti, Soujanya Chatti)

PreJudge is an AI agent that audits a hackathon submission before the real judges see it. Paste a
public GitHub repo URL and in about 5 seconds you get a judge-readiness score (0–100) mapped to the
official neatHack rubric, a fix list ordered by the points each fix is worth, and a short roast
that has to quote facts from your repo. Ask for the deep check and the agent downloads a read-only
copy of the repo, pulls the claims out of your README and tries to prove or disprove each one with
`file:line` evidence, then rescores. It never runs the audited code, and the README is never
accepted as proof of its own claims. The result is a shareable page with a roast card (PNG + link
preview).

> 🎬 **Demo video (≤ 3 min):** _link coming Monday, Oct 12_

## New tonight (Oct 12)

- **Demo script generator**: "Write my 3-minute demo script" on the result page. One LLM call,
  grounded only in the audit's facts: 7 timed scenes (3:00 total) with what to show and what to
  say, covering architecture, neatlogs (runtime + reasoning), Entire (implementation), cfo.ai and
  the before/after result. Missing evidence is always a TODO (code decides, not the model), links
  that aren't in the audit are removed, and it falls back to a template when the AI budget is out.
- **Judge panel** under the score: an Observability, a Dev-workflow and a Business judge (generic
  personas, never real people), each with one sentence of praise and one specific fix from the audit.
- **MCP server** ([mcp/](mcp/README.md)): `audit_repo`, `deep_check`, `get_result` and `next_fix`
  for Claude Code, Cursor or any MCP client, over our public API and its rate limits.
- **GitHub Action** ([docs/github-action.md](docs/github-action.md)): score and top fixes in the job
  summary on every push; never blocks a build. Running on this repo.
- **Sponsor Depth Scorecard** on every result: neatlogs, Entire and cfo.ai each get a level from 1
  (mentioned) to 4 (used to improve the project), computed from the checks only, with the reason
  and one next step. When unsure it shows the lower level.
- **Glass box**, "How this verdict was made": every agent step with its time, tokens and cost (at
  Groq list price), plus retries, fallbacks and quota waits. Built from our stored step log, the
  same steps neatlogs traces; no prompts, keys, IPs or raw errors.
- **[/transparency](https://3-82-224-157.sslip.io/transparency)**: live aggregate numbers (audits,
  repos, tokens, cost and time per quick and deep audit, fallback rate, tokens saved by reuse)
  against our [cfo.ai plan](https://cfo.ai/s/xBCsLLiMtconXUBf)'s $0.0095 per audit.
- **"Write my cfo.ai prompt"**: a ready-to-paste prompt for Ari with the pricing, cost and usage
  numbers from your README, `[___]` for the rest (the model can't add numbers), and a reminder to
  export and link the plan.
- **[/built-with](https://3-82-224-157.sslip.io/built-with)**: our build story from git and Entire:
  commits, every checkpoint linked on entire.io, and the before/after improvements linked to their
  commits and checkpoints.
- **Integrity checks** (separate section, never part of the score): does the evidence match what
  we can observe? X and Discord post dates decoded from their IDs, the demo video's publish date
  (YouTube Data API), entire.io/GitHub links that point to another repo, quoted checkpoint IDs vs
  pushed refs, commit dates vs push times, single-commit code dumps, commits dated before the repo
  existed, reused or placeholder screenshots, and before/after % / × math. Each says ok, "needs a
  human look" or "couldn't check", with the reason, the evidence and how to clear it if it's innocent
  (a rebase, a template). Near-duplicate READMEs across repos are listed on /admin only. Eval:
  9/9 faked fixtures flagged, 9/9 innocent look-alikes cleared; this repo: 10/10 ok.
- Also today: no more layout shift (live audit CLS 0.90 → 0), opt-in "Fresh off the grill" feed,
  submission post draft, README badge and a copy-paste Evidence section.

Each feature has a flag, on by default (`FEATURE_DEMO_SCRIPT`, `FEATURE_JUDGE_PANEL`,
`FEATURE_SPONSOR_SCORECARD`, `FEATURE_GLASS_BOX`, `FEATURE_TRANSPARENCY`, `FEATURE_ARI_PROMPT`, `FEATURE_INTEGRITY`,
and `VITE_FEATURE_BUILT_WITH` at build time), and every deploy keeps the previous version for
`scripts/rollback.sh`. Attaching "this verdict is wrong" feedback to the neatlogs trace was left
out: neatlogs' feedback endpoints accept only a user's OAuth token, not a project API key.

## How it works

```mermaid
flowchart LR
    U[Repo URL] --> Q
    subgraph Q[Quick phase · about 5 s · at most 1 LLM call]
        G[GitHub API: repo, README, tree, commits, Entire refs] --> C[13 deterministic rubric checks]
        L[Link checker: SSRF-safe] --> C
        V[Video length from metadata] --> C
        C --> S1[Deterministic score] --> R1[Verdict + roast, fact-checked]
    end
    R1 --> P1[(SQLite: quick_ready)]
    P1 -->|Run deep check| D
    subgraph D[Deep phase · queued one at a time]
        T[Tarball, read-only, 30 MB cap] --> X[Extract README claims]
        X --> PS[Code pre-searches every claim]
        PS --> A[Agent tools: search_repo, read_file, list_files, get_commits, check_link]
        A --> J[Each claim: verified / unverified / contradicted + evidence]
        J --> S2[Rescore + capped estimates] --> R2[Final verdict]
    end
    R2 --> P2[(SQLite: complete)]
    P2 --> O[Result page, roast card PNG, /r/id link preview]
```

**Quick phase** (`backend/app/audit.py`): reads the repo through the GitHub API and runs 13
deterministic checks from `backend/app/tools/rubric.py`. They cover commits inside the hackathon
window, neatlogs in the dependencies, trace links, Entire checkpoints, the cfo.ai plan, demo video
length, building-in-public posts, before/after numbers, a failure-and-recovery run, dead links and
prompt injection. Then one LLM call writes the verdict and roast. The result is saved straight
away, so the deep phase never holds it up.

**Deep phase** (`backend/app/agent/loop.py`): downloads the repo tarball once (size-capped;
binaries, `node_modules`, vendored code, lockfiles, symlinks and path traversal are skipped),
extracts the README's claims and verifies each one with the agent tools in
`backend/app/agent/tools.py`. `search_repo` (`backend/app/tools/search.py`) returns `file:line`
snippets with context. A claim only counts as verified when the agent cites evidence it actually
saw in the code; citing the README is not enough. The failure-and-recovery check is judged here
too (`verify_failure_recovery()` in `rubric.py`): a described run, what failed and what the agent did
next, must be backed by a trace link, a screenshot in the repo, a log or retry/fallback code. The
quick phase never scores it, so no one loses points for what it can't read.

**Scoring** (`backend/app/scoring.py`) is plain code with the rubric weights: agent 30%, neatlogs +
Entire + cfo.ai 25%, demo video 20%, building in public 15%, usefulness 10%. The LLM never sets the
score. The two things code can't measure (agent quality, usefulness) get an LLM estimate that must
cite evidence. It is labelled "estimated" and capped at 80% of those points. When a check can't be
verified automatically (for example, no Entire checkpoints found), it isn't scored and its weight
moves to the rest of the category. That way PreJudge never takes points away for something it
couldn't see.

**Safety:** repo content is untrusted data in delimited blocks. Instructions hidden in a README
are detected, flagged on the result page and cannot move the score. Links are fetched behind an
SSRF guard: `_host_problem()` in `backend/app/tools/links.py` refuses any host that resolves to a
private, loopback, link-local (this includes the cloud metadata address 169.254.169.254),
reserved, multicast or unspecified address. Redirects are followed by hand, so every hop is
checked again.

**Running on the Groq free tier** (`backend/app/llm.py`): it rotates across models and schedules
calls from the rate-limit headers. On a failure, `_classify()` sorts the error (for example
`rate_limited` for a 429), and `_on_failure()` puts that model on a cooldown for as long as the
`retry-after` header says (read by `_retry_after()`). The call then moves to the next model,
recorded as an `llm.<purpose>.fallback` step. Other errors get exponential backoff with jitter. Deep checks wait for budget rather than drop to a weaker model. Failures are
recorded as steps, and the user always gets at least a partial report. Per-IP limits, a deep-queue
cap and a per-repo cooldown protect the shared budget (`backend/app/limits.py`).

**Protecting the budget and reusing results** (M6):
- **Daily caps** (env): total deep checks per day, 3 per repo per day, and a token cap for public
  traffic. The admin reserve is kept separate. Every limit answers with a friendly message ("Today's
  deep checks are used up. Your quick result is ready; try the deep check tomorrow").
- **Same commit, same result:** if a repo's latest commit (and the check logic) hasn't changed,
  PreJudge hands back the stored audit with no LLM calls, however old it is ("No new commits since
  your last check 3 hours ago…"). Tokens saved this way are counted. A deep check whose claim judging
  failed is never reused.
- **Priority:** repos with commits inside the hackathon window go first in the deep queue.
- **Progress:** a re-check after a push shows "+22 since your last check (46 → 68)" and the checks that
  were fixed. Quick scores are compared with quick ones and deep with deep. A positive delta also
  appears on the roast card.
- **Percentiles:** "Your score beats 62% of neatHack repos we've checked", plus per-check rates such as
  "Only 34% of teams have a demo under 3:00". These are anonymous: computed over the latest real audit
  of each repo with commits in the window, shown only from 15 repos, never naming a repo, and with no
  leaderboard.
- **`/admin`** (token kept in memory only): budget per model, deep checks against the cap, queues,
  tokens saved, limit hits, projects, recent audits, feedback and per-day metrics.

## How we use neatlogs, Entire and cfo.ai

### neatlogs
Every audit is traced with the [neatlogs](https://neatlogs.com) SDK (`backend/app/tracing.py`):
each LLM call, tool call, retry, fallback and failure is recorded under the audit id as the session
id. Traces are tagged `real`/`test` and `prod`/`dev`, and secrets are masked before anything leaves
the process. The before/after numbers below come from these traces, and the M2 baseline's 16 failed LLM
calls showed up there too.

### Entire
Entire is enabled in this repo for Claude Code, and checkpoints are pushed to GitHub as
`refs/entire/checkpoints/...`.

- **Checkpoint ID:** `01M4NAH03T910P25SNH7F47SQC` (the `Entire-Checkpoint` trailer on commit `72021ab`)
- **Checkpoint link:** https://entire.io/gh/DurgaPritam/neatHack-QBITS-/commit/72021ab9bde0ea44f40c07637befa7d5228c1180
- Earlier Claude Code sessions (before Entire was enabled) were imported with `entire import
  claude-code` after a secret scan, so the whole build history is searchable.

We set this repo up following the [neatHack Entire guide](https://hack.entire.io/neathacks-2026/).
PreJudge also checks Entire for other teams: it reads the `Entire-Checkpoint` commit trailers and
the pushed `refs/entire/checkpoints` storage described in the
[Entire docs](https://docs.entire.io/guides/checkpoints/checkpoint-storage).

### cfo.ai
We built the business plan in cfo.ai: [shared model](https://cfo.ai/s/xBCsLLiMtconXUBf) ·
summary in [docs/business-plan.md](docs/business-plan.md).

- **Pricing:** monthly licenses at $199 / $499 / $999, pay-per-event audits at $49 / $149, and a
  free tier for individual teams.
- **Costs:** AI costs $0.0095 per audit, blended (measured in our traces: $0.005 quick, $0.02
  deep), and hosting is $20/month.
- **Revenue:** paid sales start Jan 2027. In the Main scenario that reaches $24,651/month by Sep
  2028 at a 96.6% gross margin.
- **Runway:** bootstrapped from $500 of starting cash. The Main scenario is profitable every month
  from Feb 2027 and never runs out of cash: its lowest point is $248 (Jan 2027), and it holds
  $88,022 by Sep 2028.

The model changed our decisions. Replacing a $0.40-per-audit AI guess with the measured cost moved
break-even 9 months earlier (v2 → v3).

## Evidence

All numbers come from real runs. Audit ids double as neatlogs session ids. The full, judge-ready
evidence page is [EVIDENCE.md](EVIDENCE.md), organised by the judging criteria:

| Criterion | Evidence |
|---|---|
| Summary and best evidence | [EVIDENCE §1](EVIDENCE.md#1-summary) |
| The agent (30%): how it works, failure and recovery runs, milestones | [EVIDENCE §2](EVIDENCE.md#2-the-agent-30) |
| neatlogs, Entire and cfo.ai (25%) | [neatlogs](EVIDENCE.md#neatlogs) · [Entire](EVIDENCE.md#entire) · [cfo.ai](EVIDENCE.md#cfoai) |
| Before/after improvements, self-audit score progression | [EVIDENCE §4](EVIDENCE.md#4-beforeafter-improvements) |
| Demo video (20%) | [EVIDENCE §5](EVIDENCE.md#5-demo-video-20) |
| Building in public (15%), production usage | [EVIDENCE §6](EVIDENCE.md#6-building-in-public-15) |
| Usefulness and originality (10%) | [EVIDENCE §7](EVIDENCE.md#7-usefulness-and-originality-10) |
| Security and privacy | [EVIDENCE §8](EVIDENCE.md#8-security-and-privacy) |

### Before → after

Before → after on openai/swarm: first result in 52s before the two-speed redesign, 5.5s after it.

| Change (repo) | Before | After |
|---|---|---|
| M2 model + loop changes (openai/swarm) | 40,086 tokens, 106 s, 0 of 8 claims checked, 16 failed LLM calls | 19,066 tokens, 52 s, claims verified with `file:line` evidence |
| Two-speed audits: time to first result (openai/swarm) | 52 s | 5.5 s (quick phase, 4,094 tokens) |
| Tarball + `search_repo` + code pre-search: verified claims (huggingface/smolagents) | 1 of 8 | 6 of 8 (`b8e64c021d56`) |
| Quick phase capped at one LLM call (openai/swarm) | 4,094 tokens | 2,154 tokens, 5.5 s |
| Production, this repo (`29def6e19f64`) | — | quick 2,173 tokens / 5.3 s; deep 17,232 tokens / 40.5 s; 6 of 6 claims verified |

### Eval: claim-judging accuracy (M5)

`cd backend && python -m evals.run` audits a labelled eval set (our repo, three big public repos and
five neatHack submissions anonymised as Repo A-E) and scores every verdict against hand labels
(AI-assisted, spot-checked by the team). On the first labelled repo, langchain-ai/open_deep_research,
the 9 rubric checks were all right, but the claim judge was too strict. After five fixes (no
goalpost-moving, config files as evidence, commands aren't claims, no README as proof, faithful
claim text):

| | Rubric checks | Claims correct | Claim false fails | Claim false passes |
|---|---|---|---|---|
| Before (`d9ee0299389d`) | 9/9 | 3/8 (37.5%) | 4 | 1 |
| After, latest run (`26d849e7c7aa`) | 9/9 | 5/5 (100%) | 0 | 0 |
| After, all 5 runs | 9/9 each | 80–100% | 0–1 | 0 |

One labelled repo so far, so these are small numbers; every run is in [EVIDENCE.md](EVIDENCE.md).

### Failure and recovery in production (audit `29def6e19f64`)

During the deep check of this repo, the claim-judging call `llm.verify` on `qwen/qwen3.8-27b`
**failed with a Groq 429 (rate limit)**. The agent backed off, retried on the fallback model
`openai/gpt-oss-120b` (3 calls, 9,018 prompt tokens) and finished the audit: 46/100 with 6 of 6
claims verified. The failed call is a recorded step on the public result page
https://3-82-224-157.sslip.io/a/29def6e19f64 and in the neatlogs trace for session `29def6e19f64`.

The same pattern on Oct 12, as neatlogs shows it:

![neatlogs trace: failed steps flagged, agent recovered](evidence/neatlogs-failure-recovery.jpeg)
*neatlogs trace of a deep audit (Oct 12, 11:40 IST, 19 steps, 42.9 s): `github.download_tarball`, a `qwen/qwen3.8-27b` call and `agent.search_repo` failed and are flagged "Execution Failed"; the agent fell back to `openai/gpt-oss-120b` and other tools and finished.*

### neatlogs traces

Trace links (these need a neatlogs login, so screenshots follow):
[trace 1](https://app.neatlogs.com/traces/1458d983f3b529fecc4f3802366a96dc?orgId=c6ad6e53-b608-4914-80dd-1431f37951b6&projectId=91fff568-d321-45b8-83de-035100300128) ·
[trace 2](https://app.neatlogs.com/traces/b044efa9359e61ecef04ed7f61e9e216?orgId=c6ad6e53-b608-4914-80dd-1431f37951b6&projectId=91fff568-d321-45b8-83de-035100300128) ·
[trace 3](https://app.neatlogs.com/traces/c659bf9a4d3ef652dbc334dba40df89c?orgId=c6ad6e53-b608-4914-80dd-1431f37951b6&projectId=91fff568-d321-45b8-83de-035100300128)

![neatlogs traces list: 5,536 traces](evidence/neatlogs-traces-list.jpeg)
*The neatlogs traces list for PreJudge: 5,536 traces captured by Oct 12, 21:35 IST (repo URLs in, verdicts out).*

![neatlogs trace: 13-step deep audit span tree](evidence/neatlogs-span-tree.jpeg)
*One full deep audit in neatlogs (13 steps, 29.3 s): tarball download, claim extraction, claim verification and verdict, with the model, tokens and cost of every LLM call.*

## Building in public

- **#neatHack launch thread on X:** https://x.com/PritamLite/status/2109287438342582620
- **Feature update on X:** https://x.com/PritamLite/status/2109658774336409974
- Production usage and other teams' progress (anonymous): [EVIDENCE §6](EVIDENCE.md#6-building-in-public-15)

## Run it yourself

```bash
cd backend && python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # add GROQ_API_KEY, GITHUB_TOKEN, NEATLOGS_API_KEY
.venv/bin/uvicorn app.main:app --port 8000
cd ../frontend && npm install && npm run dev      # http://localhost:5173
```

- CLI: `cd backend && .venv/bin/python -m app.cli <repo_url> --full`
- Tests: `cd backend && .venv/bin/python -m pytest` (266 tests) and `cd frontend && ./e2e/run.sh`
  (Playwright, replay mode, no LLM tokens)
- Deploy: [DEPLOY.md](DEPLOY.md) (EC2, Docker Compose, Caddy HTTPS, daily backups)

## Repo layout

| Path | What's there |
|---|---|
| `backend/app/tools/` | GitHub client, rubric checks, link checker, repo search, video metadata |
| `backend/app/agent/` | deep-phase agent loop, prompts, claim schemas, roast rules |
| `backend/app/scoring.py` | deterministic scoring |
| `backend/app/main.py` | FastAPI routes, abuse limits, admin endpoints |
| `frontend/` | React + Vite + TypeScript UI, roast card export |
| `deploy/`, `scripts/` | Docker Compose, Caddyfile, server setup, deploy script |
| `docs/business-plan.md` | cfo.ai business plan summary |
| `EVIDENCE.md` | traces, before/after numbers, throughput, failure runs |
