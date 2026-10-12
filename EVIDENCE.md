# PreJudge: evidence

Every number below comes from this repo, its git history, the eval result files or production
data, and each one links to its source. Audit ids double as neatlogs session ids. Ids that link
to `https://3-82-224-157.sslip.io/a/<id>` are public result pages, where every step (including
failures) is listed. Ids without a link were local or eval runs: their record is the neatlogs
session, which needs a neatlogs login. Anything we couldn't back with a source is marked **TODO**.

Commit links: `https://github.com/DurgaPritam/neatHack-QBITS-/commit/<sha>`.
Production figures were read from `/api/admin/metrics` and `/api/admin/overview` on
**2026-10-12 15:08 UTC**.

## Contents
1. [Summary](#1-summary)
2. [The agent (30%)](#2-the-agent-30)
3. [neatlogs, Entire and cfo.ai (25%)](#3-neatlogs-entire-and-cfoai-25): [neatlogs](#neatlogs) · [Entire](#entire) · [cfo.ai](#cfoai)
4. [Before/after improvements](#4-beforeafter-improvements)
5. [Demo video (20%)](#5-demo-video-20)
6. [Building in public (15%)](#6-building-in-public-15)
7. [Usefulness and originality (10%)](#7-usefulness-and-originality-10)
8. [Security and privacy](#8-security-and-privacy)
9. [Appendix: detailed runs](#9-appendix-detailed-runs)

---

## 1. Summary

**PreJudge** audits a hackathon submission before the judges see it. Paste a public GitHub repo
and in about 5 seconds you get a judge-readiness score (0–100) mapped to the neatHack rubric, a
fix list ordered by points, and a roast that must quote facts from your repo. The optional deep
check reads the code and proves or disproves each README claim with `file:line` evidence. It never
runs the audited code.

- **Live:** https://3-82-224-157.sslip.io
- **Team QBITS:** Durga Pritam Suggisetti and Soujanya Chatti
- **Repo:** https://github.com/DurgaPritam/neatHack-QBITS-

**Best evidence**
1. **Failure and recovery in production:** a Groq 429 in claim judging fell back to another model,
   and the audit still finished with 6/6 claims verified ([audit `29def6e19f64`, steps 13–14](https://3-82-224-157.sslip.io/a/29def6e19f64)). [→ §2](#failure-and-recovery-runs)
2. **neatlogs-measured cost reshaped the business plan:** $0.0095 per audit against a $0.40 guess
   moved break-even 9 months earlier in cfo.ai (v2 → v3). [→ cfo.ai](#cfoai)
3. **Measured speed-ups:** deep tokens went from 40,086 to 10,145 (openai/swarm), the first
   result went from 52 s to 5.5 s, and verified claims on smolagents rose from 1/8 to 6/8. [→ §4](#4-beforeafter-improvements)
4. **Claim-judge accuracy:** 37.5% → 80–100% on a labelled repo, from the eval result files. [→ §4](#4-beforeafter-improvements)
5. **Real use by other teams:** 58 roasts of 12 repos, with one team re-checking its way from
   36 to 92 (anonymous). [→ §6](#6-building-in-public-15)

---

## 2. The agent (30%)

### How it works
- **Quick phase** ([`backend/app/audit.py`](backend/app/audit.py)): GitHub API reads, 13
  deterministic rubric checks ([`backend/app/tools/rubric.py`](backend/app/tools/rubric.py)), an
  SSRF-safe link checker ([`backend/app/tools/links.py`](backend/app/tools/links.py)), demo
  length from video metadata ([`backend/app/tools/video.py`](backend/app/tools/video.py)), then
  **at most one** LLM call for the verdict and roast. The roast is fact-checked before it's shown.
- **Deep phase** ([`backend/app/agent/loop.py`](backend/app/agent/loop.py)): the repo tarball is
  read in memory (30 MB cap; binaries, vendored code, lockfiles, symlinks and path traversal
  skipped), README claims are extracted, code pre-searches every claim, and the agent verifies each
  one with its tools ([`backend/app/agent/tools.py`](backend/app/agent/tools.py)):
  `search_repo`, `read_file`, `list_files`, `get_commits` and `check_link`. A claim only counts as
  verified when the cited evidence was actually observed. The README never proves its own claims.
- **Deterministic scoring** ([`backend/app/scoring.py`](backend/app/scoring.py)): rubric weights in
  code. The LLM never sets the score; its two estimates (agent quality, usefulness) must cite
  evidence and are capped.
- **Never runs code:** nothing from the audited repo is executed or written to disk
  ([`backend/app/tools/search.py`](backend/app/tools/search.py)).
- **Prompt-injection protection:** repo text only reaches the model inside delimited untrusted-data
  blocks ([`backend/app/agent/prompts.py`](backend/app/agent/prompts.py)). Injection attempts are
  flagged by a rubric check and can't move the score. A test feeds a README that asks for "100/100"
  ([`backend/tests/test_agent.py`](backend/tests/test_agent.py)).
- **Rate limits:** the client rotates across Groq models, schedules calls from the rate-limit
  headers, cools a model down for its `retry-after`, and makes deep checks wait for judge-model
  budget rather than use a weaker model ([`backend/app/llm.py`](backend/app/llm.py)).

### Failure and recovery runs
All three are public result pages; the step numbers refer to the step log on each page.

| Run | What failed | What the agent did next | Outcome |
|---|---|---|---|
| [`29def6e19f64`](https://3-82-224-157.sslip.io/a/29def6e19f64) (this repo, commit [`6ab6239`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/6ab6239)) | step 13: `llm.verify` on `qwen/qwen3.8-27b` got a **Groq 429** | step 14: fell back to `openai/gpt-oss-120b`; steps 17–18 and 22 waited for quota from the rate-limit headers | complete, 46/100, **6/6 claims verified**, 17,232 deep tokens, 40.5 s |
| [`3b8b2d19878f`](https://3-82-224-157.sslip.io/a/3b8b2d19878f) (commit [`88b0282`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/88b0282)) | step 16: `verify.invalid_json`, the model returned **invalid JSON** (unterminated string) | step 18: re-asked with a condensed, tool-free final prompt on `openai/gpt-oss-120b` | complete, 64/100 |
| [`618e804d2f91`](https://3-82-224-157.sslip.io/a/618e804d2f91) (commit [`adc36de`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/adc36de)) | step 23: the roast failed the fact check; step 24: the rewrite got a **429** | step 25: fell back to `openai/gpt-oss-20b` | complete, **75/100, 8/8 claims verified** |

Earlier, before deployment, all three development models hit Groq's daily token cap; quick audits
fell back to fact-only template verdicts in 4–9 s, with each failure recorded as a step
(`rate_limited_tpd`, [§9](#throughput-on-the-groq-free-tier-measured-2026-10-10)).

![neatlogs trace: failed steps flagged, agent recovered](evidence/neatlogs-failure-recovery.jpeg)
*neatlogs trace of a deep audit (Oct 12, 11:40 IST, 19 steps, 42.9 s): `github.download_tarball`, a `qwen/qwen3.8-27b` call and `agent.search_repo` failed and are flagged "Execution Failed"; the agent fell back to `openai/gpt-oss-120b` and other tools and finished.*

### Milestones
| Milestone | What shipped | Commits |
|---|---|---|
| M1 | Backend skeleton, GitHub tool, link checker, 13 deterministic checks, CLI, tracing | [`b6c7f69`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/b6c7f69) → [`da0bcb2`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/da0bcb2) |
| M2 | Groq agent loop, claim verification, deterministic scoring, roast, API + queue + SQLite | [`7d80407`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/7d80407), [`c461c16`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/c461c16), [`4522862`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/4522862) |
| M2.5 | Model rotation, tarball + `search_repo`, two-speed audits, code pre-search | [`307f032`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/307f032), [`b387c26`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/b387c26), [`8dd435c`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/8dd435c), [`45974d7`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/45974d7) |
| M3 | React UI, roast card + share page, record/replay, e2e tests | [`01ad8a3`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/01ad8a3), [`6c504bd`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/6c504bd), [`e28c70f`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/e28c70f), [`e1815b7`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/e1815b7) |
| M4 | EC2 deploy (Docker Compose, Caddy HTTPS, backups), first production audit | [`60b96a5`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/60b96a5), [`0a7930e`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/0a7930e) |
| M5 | Labelled eval set, runner, baseline and before/after claim accuracy | [`43290b9`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/43290b9), [`38c015d`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/38c015d), [`b74a71a`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/b74a71a) |
| M6 | Daily caps, same-commit reuse, progress, percentiles, `/admin` | [`a0728cc`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/a0728cc), [`eed280e`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/eed280e) |
| Final evening | Demo script, judge panel, MCP server, GitHub Action, layout-shift fix, opt-in feed, submission kit | [`a5c3fa1`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/a5c3fa1), [`a35b584`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/a35b584), [`b8beb5b`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/b8beb5b), [`de8a709`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/de8a709), [`b2ac135`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/b2ac135), [`4b64d8f`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/4b64d8f) |

---

## 3. neatlogs, Entire and cfo.ai (25%)

### neatlogs
- **Architecture:** one tracing module, [`backend/app/tracing.py`](backend/app/tracing.py)
  ([`b6c7f69`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/b6c7f69),
  hardened in [`9ab3313`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/9ab3313)).
  Every audit runs inside an audit context whose session id is the audit id. Quick and deep phases
  are separate traces in that session.
- **Implementation:** spans for every LLM call (the OpenAI client is wrapped), every tool call,
  every retry, fallback and quota wait (as events). Runs are tagged `real`/`test` and
  `prod`/`dev`. A mask redacts secrets before export. Tests never export spans
  ([`7042bea`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/7042bea)).
- **Runtime:** production traces carry the `prod` tag; the session id of any audit below opens its
  trace. Day 1 (M1, deterministic checks only): 17 sessions, 29.4% errors, mostly intentional
  failure tests (neatlogs dashboard).
  - Trace links (neatlogs login needed):
    [trace 1](https://app.neatlogs.com/traces/1458d983f3b529fecc4f3802366a96dc?orgId=c6ad6e53-b608-4914-80dd-1431f37951b6&projectId=91fff568-d321-45b8-83de-035100300128) ·
    [trace 2](https://app.neatlogs.com/traces/b044efa9359e61ecef04ed7f61e9e216?orgId=c6ad6e53-b608-4914-80dd-1431f37951b6&projectId=91fff568-d321-45b8-83de-035100300128) ·
    [trace 3](https://app.neatlogs.com/traces/c659bf9a4d3ef652dbc334dba40df89c?orgId=c6ad6e53-b608-4914-80dd-1431f37951b6&projectId=91fff568-d321-45b8-83de-035100300128)
  - **5,536 traces captured** by Oct 12, 21:35 IST (neatlogs traces list, below).
  - Screenshots (the trace links need a login):

    ![neatlogs traces list: 5,536 traces](evidence/neatlogs-traces-list.jpeg)
    *The neatlogs traces list for PreJudge: 5,536 traces captured by Oct 12, 21:35 IST (repo URLs in, verdicts out).*

    ![neatlogs trace: 13-step deep audit span tree](evidence/neatlogs-span-tree.jpeg)
    *One full deep audit in neatlogs (13 steps, 29.3 s): tarball download, claim extraction, claim verification and verdict, with the model, tokens and cost of every LLM call.*

    The failure-and-recovery trace is in [Failure and recovery runs](#failure-and-recovery-runs).
- **Reasoning:** the traces showed where the tokens and time went, and each fix targeted what they
  showed:

  | Change (openai/swarm unless noted) | Before | After | Source |
  |---|---|---|---|
  | Primary model gpt-oss-120b → qwen3.8-27b (parallel tool calls) + 3-turn cap + condensed final answer | 40,086 tokens, 106 s, claims never judged, 16 failed LLM calls | 19,066 tokens, 52 s, 4/7 claims verified | session `4c5f0f5b9cf9` (after); [`7d80407`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/7d80407) |
  | Two-speed audits: first result | 52 s (single phase) | 5.5–12 s (quick phase) | sessions `3c94ce84b8a5`, [`4d5dbd1bf972`](https://3-82-224-157.sslip.io/a/4d5dbd1bf972); [`8dd435c`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/8dd435c) |
  | Deep phase tokens / total time | 40,086 tokens / 106 s | 10,145 deep tokens / 36.7 s total (6.1 s quick + 30.6 s deep) | [`4d5dbd1bf972`](https://3-82-224-157.sslip.io/a/4d5dbd1bf972) |
  | Code pre-search of every claim (huggingface/smolagents) | 0/8 verified at 20.8k–23.8k deep tokens (gpt-oss makes one tool call per turn) | 4–6/8 verified at 10–18k | [`45974d7`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/45974d7); session `b8e64c021d56` |

- **Result:** production deep checks on this repo now take 39–45 s and 17–25k tokens
  ([`29def6e19f64`](https://3-82-224-157.sslip.io/a/29def6e19f64),
  [`3b8b2d19878f`](https://3-82-224-157.sslip.io/a/3b8b2d19878f)), and the latest verified **8/8** claims ([`618e804d2f91`](https://3-82-224-157.sslip.io/a/618e804d2f91)).
- **TODO:** the neatlogs "Execution Failed" detection catching a real failure. There's no record of
  it in the repo yet; add a screenshot or trace link.
- **Not built:** a public "glass box" / transparency page. The closest live feature is the public
  step log on every result page, which lists every step including failures.

### Entire
- **Enabled** for Claude Code with the hooks and settings committed
  ([`72021ab`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/72021ab)). Checkpoints are
  pushed to GitHub as `refs/entire/checkpoints/<shard>/<id>`, following the
  [neatHack Entire guide](https://hack.entire.io/neathacks-2026/) and the
  [checkpoint storage docs](https://docs.entire.io/guides/checkpoints/checkpoint-storage).
- **Checkpoint count:** **41** checkpoint refs on GitHub, and 41 commits carry an
  `Entire-Checkpoint` trailer (`git ls-remote origin 'refs/entire/checkpoints/*'`, 2026-10-12).
- **Checkpoint link + ID (also in the README):** ID `01M4NAH03T910P25SNH7F47SQC`, the trailer on
  commit `72021ab`:
  https://entire.io/gh/DurgaPritam/neatHack-QBITS-/commit/72021ab9bde0ea44f40c07637befa7d5228c1180.
  The latest is `01M4R9F71K78EMWF1JRZPKPNGM` on
  [`7cfd839`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/7cfd839).
- **Onboarded on entire.io** (mirrored on aws-ap-south-1 and aws-us-east-2), after which the
  checkpoint link returns HTTP 200
  ([`30b9686`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/30b9686)).
- **History import with redaction:** 2 Claude Code sessions from before Entire was enabled
  (15 turns) were imported with `entire import claude-code`. One transcript held pasted API keys, so
  a local, gitignored redaction pack was added first. All checkpoint blobs were rescanned before
  pushing: 0 secret matches
  ([`a354832`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/a354832)).
- **Checking other teams:** PreJudge's Entire check reads `Entire-Checkpoint` commit trailers, the
  pushed `refs/entire/checkpoints` storage and checkpoint links in the README
  ([`f382521`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/f382521),
  `check_entire()` in [`rubric.py`](backend/app/tools/rubric.py)). On our own repo it went from "none found (not scored)" to
  **pass** ([`3b8b2d19878f`](https://3-82-224-157.sslip.io/a/3b8b2d19878f)).

### cfo.ai
- **Model:** https://cfo.ai/s/xBCsLLiMtconXUBf · summary in
  [docs/business-plan.md](docs/business-plan.md) · Ari's raw notes in
  [docs/cfo-ai-notes-raw.md](docs/cfo-ai-notes-raw.md)
  ([`2fd174b`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/2fd174b), final v3 in
  [`b826ff3`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/b826ff3)).

| Headline (Main scenario) | v1: first draft | v2: business model added | v3: final |
|---|---|---|---|
| AI cost per audit | $0.40 (estimate) | $0.40 (placeholder split) | **$0.0095 (measured)** |
| Funding | $150k raise May 2027 | bootstrapped | bootstrapped |
| Profitable every month from | Nov 2027 | Nov 2027 | **Feb 2027** |
| Lowest cash | $322 | −$482 | **$248** (Jan 2027) |
| Runway | OK only because of the raise | runs out Jan–Mar 2027 | **never runs out** |
| Gross margin, Sep 2028 | 85% | 83% | **96.6%** |
| Monthly revenue, Sep 2028 | $22,992 | $23,905 | **$24,651** |
| Cash, Sep 2028 | $193,878 (incl. raise) | $43,824 | **$88,022** |

- **How neatlogs changed the plan:** the traces measured about 2.6k tokens per quick audit and
  about 15k per deep audit ([§9](#throughput-on-the-groq-free-tier-measured-2026-10-10)). At
  Groq's list price for our main model, qwen3.8-27b, that is about $0.003–0.005 per quick audit and
  $0.018 per deep audit. The plan uses the rounded upper bound: **$0.005 quick and $0.02 deep,
  $0.0095 blended** at 70% quick-only, about **42× below** the $0.40 guess. Plugged into cfo.ai with $20/month
  hosting, it moved break-even **9 months earlier** (Nov 2027 → Feb 2027) and closed v2's cash gap.
- **Pricing decision it led to:** size-based event pricing ($49 up to 50 teams, $149 for 51–300)
  replaced a flat $49 that lost money above about 122 teams at the old cost, raising revenue per
  event by about 80%. The cheap measured AI is what made a 10× bigger free tier affordable (500 →
  5,000 audits/month). See [docs/business-plan.md](docs/business-plan.md).
- **Starting cash:** $500 (final). Main never runs out; its lowest point is $248 in Jan 2027.
- **Not built:** a public plan-vs-actual transparency page.
- 📸 **TODO:** cfo.ai screenshots (`evidence/cfo-*.png`) and a model export (`docs/cfo-ai-model.*`).

---

## 4. Before/after improvements

| Improvement | Before | After | Source |
|---|---|---|---|
| Deep tokens, openai/swarm | 40,086 | 10,145 | session `4c5f0f5b9cf9`, [`4d5dbd1bf972`](https://3-82-224-157.sslip.io/a/4d5dbd1bf972), [`8dd435c`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/8dd435c) |
| Total time, openai/swarm | 106 s | 36.7 s (first result after 6.1 s) | same |
| Quick phase capped at one LLM call | 4,094 tokens | 2,154 tokens, 5.5 s | [`dbec90c`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/dbec90c) |
| Verified claims, huggingface/smolagents | 1/8 (M2) | 6/8 (run A) · 3/8 (run B) | session `b8e64c021d56`, [`fa16370b7b8b`](https://3-82-224-157.sslip.io/a/fa16370b7b8b), [`45974d7`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/45974d7) |
| Claim-judge accuracy on a labelled repo (labels AI-assisted, spot-checked by the team) | 37.5% (3/8), 4 false fails, 1 false pass | 100%, 87.5%, 83.3%, 80%, 100% over 5 runs | [`baseline.json`](backend/evals/results/2026-10-11-baseline.json) · [`after-5.json`](backend/evals/results/2026-10-11-after-5.json) · [`16a2b6f`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/16a2b6f), [`b74a71a`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/b74a71a) |
| Layout shift (CLS), live audit page | 0.90 desktop / 0.51 mobile | 0 / 0 on every page and width | [`a5c3fa1`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/a5c3fa1), [`42f48e2`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/42f48e2), [`frontend/e2e/cls.mjs`](frontend/e2e/cls.mjs) |
| Tokens reused in production (same commit, same result) | — | 143,059 tokens saved by 11 reused audits | `/api/admin/metrics`, [`a0728cc`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/a0728cc) |
| Demo length on EC2 (YouTube blocks yt-dlp there) | unknown | read via the YouTube Data API (12:46 for open_deep_research) | [`6c596bffbbb7`](https://3-82-224-157.sslip.io/a/6c596bffbbb7), [`5a57e11`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/5a57e11) |
| Bot-blocked links (403) | 2 false "dead" links on openai/swarm | 0 | [`6842ca6`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/6842ca6) |
| Local dev URLs | 5/33 "dead" on open_deep_research (2 were 127.0.0.1) | 3/33 | [`f0574f2`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/f0574f2) |
| README citing itself as proof | 3 circular "verified" claims | 0 | [`7d80407`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/7d80407) |

### Self-audit score progression (PreJudge on this repo, in production)
| Date | Audit | Commit | Quick | Deep |
|---|---|---|---|---|
| Oct 11 | [`29def6e19f64`](https://3-82-224-157.sslip.io/a/29def6e19f64) | [`6ab6239`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/6ab6239) | 40 | 46 |
| Oct 11 | [`5d7a44233910`](https://3-82-224-157.sslip.io/a/5d7a44233910) | [`8d76aab`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/8d76aab) | 61 | 64 |
| Oct 11 | [`3b8b2d19878f`](https://3-82-224-157.sslip.io/a/3b8b2d19878f) | [`88b0282`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/88b0282) | 62 | 64 |
| Oct 11 | [`2b98e8ffae31`](https://3-82-224-157.sslip.io/a/2b98e8ffae31) | [`a67e64a`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/a67e64a) | 64 | 68 |
| Oct 12 | [`8528201c5a75`](https://3-82-224-157.sslip.io/a/8528201c5a75) | [`41da07b`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/41da07b) | 67 | 61 |
| Oct 12 | [`618e804d2f91`](https://3-82-224-157.sslip.io/a/618e804d2f91) | [`adc36de`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/adc36de) | 67 | **75** |
| Oct 12 | [`d5a28707bd3a`](https://3-82-224-157.sslip.io/a/d5a28707bd3a) | [`7cfd839`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/7cfd839) | 67 | — |

### Bugs our own audit found (all fixed)
The self-audits caught three bugs in PreJudge itself:
- A re-audit within 10 minutes of a push returned the stale result
  ([`a908a14`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/a908a14),
  [`c80a5ed`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/c80a5ed)).
- Any neatlogs.com link counted as a trace, and before/after numbers in a table were missed
  ([`9b5d893`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/9b5d893)).

---

## 5. Demo video (20%)

- Video: https://www.youtube.com/watch?v=m2MebedTm4k ("PreJudge - Get Roasted Before The Judges Do")
- Length: **3:01** (181 s), published 2026-10-12 17:51 UTC (23:21 IST), both read from the YouTube Data API.
- Covers neatlogs, Entire and cfo.ai.

---

## 6. Building in public (15%)

- **Launch thread (#neatHack):** https://x.com/PritamLite/status/2109287438342582620
- **Feature update:** https://x.com/PritamLite/status/2109658774336409974
- **Discord #show-and-tell posts:** TODO (links)

**Usage in production** (real runs only; test runs, built-in examples and removed audits excluded):

| | |
|---|---|
| Roasts | **58** |
| Unique repos | **12** |
| Deep checks | 20 requested, 19 completed |
| Roast card downloads | 3 |
| Share on X clicks | 1 |
| Public LLM tokens | 237,437 |
| Tokens saved by same-commit reuse | 143,059 (11 audits) |
| "This verdict is wrong" reports | 1 (on the commit-window check) |

**Other teams, anonymously** (score sequences from `/api/admin/overview`):
- One team re-checked 14 times in about four hours and went from **36 to 92**
  (36 → 55 → 63 → 68 → 92 on the deep check).
- Others: 62 → 73, 79 → 91 and 36 → 44.

---

## 7. Usefulness and originality (10%)

**Who it helps:** every team in the final hours before the deadline (what's missing, ordered by
points, with evidence), and organizers as a pre-check that flags missing tool evidence, dead links,
an over-long demo or prompt injection before judging.

**Live features** (each checked against production on 2026-10-12):
- **Submission kit** (post draft, README badge, copy-paste Evidence section):
  [`b8beb5b`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/b8beb5b). Example badge:
  `https://3-82-224-157.sslip.io/badge/DurgaPritam/neatHack-QBITS-.svg`.
- **Score progress** ("+22 since your last check", quick vs quick and deep vs deep):
  [`eed280e`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/eed280e),
  [`09f0f08`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/09f0f08).
- **Demo script generator** and **judge panel** (three generic personas):
  [`de8a709`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/de8a709). On our audit
  `618e804d2f91` the script was LLM-written: 3:00, 7 scenes, 0 TODOs.
- **MCP server** ([mcp/](mcp/README.md)): `audit_repo`, `deep_check`, `get_result`, `next_fix`
  ([`b2ac135`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/b2ac135)). Tested end to end
  against production.
- **GitHub Action** ([docs/github-action.md](docs/github-action.md)): score and top fixes in the job
  summary on every push ([`4b64d8f`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/4b64d8f)),
  running on this repo: [Actions](https://github.com/DurgaPritam/neatHack-QBITS-/actions).
- **Opt-in "Fresh off the grill" feed** of roasts their owners chose to show
  ([`a35b584`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/a35b584)).
- **Anonymous percentiles** ("beats 62% of neatHack repos"): built
  ([`a0728cc`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/a0728cc)), but not shown yet.
  The pool only counts repos with commits inside the hackathon window, and it needs 15; production
  has 8.

**In progress (not deployed):** sponsor depth scorecard and an Ari (cfo.ai) prompt helper.

**The bigger goal:** fair, evidence-based judging. Every point is tied to a check or a cited
`file:line`, the score is code rather than an LLM's opinion, and the README can't vouch for itself.

---

## 8. Security and privacy

- **Secrets never committed:** keys only in `.env` (gitignored). A pre-publication scan checked
  every blob in the git history and all Entire checkpoint data against the exact `.env` values and
  common key patterns: 0 real secrets
  ([`a354832`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/a354832)).
- **Key rotation:** the procedure is in [DEPLOY.md](DEPLOY.md). **TODO:** confirm the keys that were
  pasted into an early chat session have been rotated.
- **Redacted checkpoints:** the imported Entire sessions were redacted and rescanned before pushing
  ([§3 Entire](#entire)).
- **No personal data stored:** no accounts. Daily counters hold no per-user data and no cookies
  ([`backend/app/db.py`](backend/app/db.py)). Client IPs for rate limiting stay in memory and are
  never written to disk ([`backend/app/limits.py`](backend/app/limits.py)). Result pages are
  `noindex`, and so is `/admin`
  ([`6ab6239`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/6ab6239),
  [`04cdc47`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/04cdc47)).
- **Removal option:** a removal request hides a result page (HTTP 410), and an admin can restore it ([`6ab6239`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/6ab6239)).
  Hidden audits right now: 0.
- **Other teams anonymised:** eval repos are "Repo A–E", with their URLs in a gitignored file
  ([`41da07b`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/41da07b)). Percentiles never name
  a repo and there is no leaderboard. This page names no other team.
- **Opt-in homepage feed:** only roasts whose owners opted in are shown
  ([`a35b584`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/a35b584)).
- **Untrusted repo content:** SSRF guard on every link hop; prompt-injection detection
  ([§2](#2-the-agent-30)).

---

## 9. Appendix: detailed runs

### M2 full audits (local, `python -m app.cli <repo> --full`)
| Repo | Score | Claims verified | Tokens | Time | Session |
|---|---|---|---|---|---|
| openai/swarm | 27 | 4/7 | 19,066 | 52s | `4c5f0f5b9cf9` |
| huggingface/smolagents | 17 | 1/8 | 15,061 | 37s | `19605ae23560` |
| langchain-ai/open_deep_research | 32 | 4/8 | 21,172 | 34s | `f2b5f750984e` |

### M2.5: two-speed audits (2026-10-10)
| Repo | Before: tokens / time / verified | After run A: quick → deep, verified | After run B: quick → deep, verified |
|---|---|---|---|
| openai/swarm | 19,066 / 52s / 4 of 7 | 4,094 tok, 5.5s → 16,181 tok, 7.6s · **6 of 8** (`3c94ce84b8a5`) | 4,048 tok, 6.1s → 10,145 tok, 30.6s · 3 of 7 ([`4d5dbd1bf972`](https://3-82-224-157.sslip.io/a/4d5dbd1bf972)) |
| huggingface/smolagents | 15,061 / 37s / 1 of 8 | 5,812 tok, 47.5s* → 17,896 tok, 49.8s · **6 of 8** (`b8e64c021d56`) | 3,981 tok, 10.4s → 9,960 tok, 30.3s · 3 of 8 ([`fa16370b7b8b`](https://3-82-224-157.sslip.io/a/fa16370b7b8b)) |
| langchain-ai/open_deep_research | 21,172 / 34s / 4 of 8 | 4,024 tok, 11.9s → 18,159 tok, 57.8s · 3 of 8 (`909e4b969177`) | 4,235 tok, 11.7s → 18,682 tok, 80.8s · 4 of 8 ([`6dbfbb5d1c76`](https://3-82-224-157.sslip.io/a/6dbfbb5d1c76)) |

\* waited for per-minute quota on every model. Verified counts vary run to run with the model the
scheduler gets under quota pressure.

### Throughput on the Groq free tier (measured 2026-10-10)
Limits are per model: 8,000 tokens/min, 30 requests/min, 1,000 requests/day, **200,000 tokens/day**.
Three tool-calling models give 24k tokens/min and 600k tokens/day.

| | Avg tokens | Avg calls | Avg time | Burst (per hour) | Sustained over 24h |
|---|---|---|---|---|---|
| Quick audit | ~2,600 (single call) | 1–1.7 | 8–14 s | **measured 256/h** (10 audits in 141 s) | ≈ 9/h (≈ 220/day) |
| Deep audit (one at a time) | 15,170 | 4.5 | 42.8 s | ≈ 84/h | ≈ 1.6/h (≈ 40/day) |
| Full audit | ~18,000 | | | | **≈ 31–33/day** |

The binding limit is tokens per day: by the end of that day's development runs all three models
answered 429 "tokens per day (TPD): Limit 200000, Used ~199,000". Reproduce with
`python -m scripts.throughput` ([`backend/scripts/throughput.py`](backend/scripts/throughput.py)).

### Claim-judge eval runs (labelled repo: langchain-ai/open_deep_research)
| Run (session) | Fixes in place | Rubric checks | Claims correct | False fails | False passes |
|---|---|---|---|---|---|
| Baseline `d9ee0299389d` | none | 9/9 | 3/8 (37.5%) | 4 | 1 |
| After 1 `e166d6c4a643` | prompts, config presearch, command filter | 9/9 | 6/6 (100%) | 0 | 0 |
| After 2 `55cddb3e68c6` | same | 9/9 | 7/8 (87.5%) | 1 | 0 |
| After 3 `da5768158590` | + config hits for every claim | 9/9 | 5/6 (83.3%) | 1 | 0 |
| After 4 `c31e614f93da` | + no numbers the quote lacks | 9/9 | 4/5 (80%) | 1 | 0 |
| After 5 `26d849e7c7aa` | + stitched quotes cut | 9/9 | 5/5 (100%) | 0 | 0 |

One labelled repo (8 claims), so these are small numbers. Claims are re-extracted every run, so
0–3 labelled claims per run weren't extracted again and aren't scored. Result files:
[`backend/evals/results/`](backend/evals/results/).

### Production smoke test (M4, 2026-10-11)
All passed: quick audit, deep check, card.png (1200×630), `/r/{id}` Open Graph preview and
redirect, Download PNG and Share on X in a real browser, removal → 410 → admin restore, feedback
CSV export, metrics counters, per-IP limit (6th audit in 10 min → 429 with Retry-After), repo
cooldown, nonexistent repo, unknown audit id, CORS rejects other origins, noindex headers, daily
backup written ([`531f542`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/531f542),
[`0a7930e`](https://github.com/DurgaPritam/neatHack-QBITS-/commit/0a7930e)).

### Final evening features and how each was verified (Oct 12)
| Feature | Tests | Verified in production |
|---|---|---|
| Demo script generator (`FEATURE_DEMO_SCRIPT`) | `test_extras.py` + e2e | audit `618e804d2f91`: LLM-written, 3:00, 7 scenes, 0 TODOs |
| Judge panel (`FEATURE_JUDGE_PANEL`) | `test_extras.py` + e2e (3 personas, CLS < 0.1) | same audit: 3 personas, each with praise and a fix grounded in the audit |
| MCP server ([mcp/](mcp/README.md)) | `mcp/test_prejudge_mcp.py`, offline + end to end over stdio | against production: audit_repo → 75/100, next_fix → demo video |
| GitHub Action ([docs/prejudge.yml](docs/prejudge.yml)) | `test_github_action.py` against a stub API | same step against production: 75/100 + top fixes in the summary |
| Sponsor Depth Scorecard (`FEATURE_SPONSOR_SCORECARD`) | `test_sponsors.py` (every level per tool; a level-4 claim must be verified and say what changed) + e2e | this repo: neatlogs 2 (trace links need a login), Entire 3, cfo.ai 3 |
| Glass box (`FEATURE_GLASS_BOX`) | `test_glass_box.py` (cost basis, retries/fallbacks, no secrets/raw errors leave) + e2e | audit `618e804d2f91`: 27,143 tokens, $0.0200 (quick $0.0027, deep $0.0173), 2 retries, 1 fallback, 2 quota waits |
| /transparency (`FEATURE_TRANSPARENCY`) | `test_transparency.py` (aggregates, no repo names, 5-min cache) + e2e | first numbers: $0.0072 per audit vs the plan's $0.0095 (25% under); quick $0.0028, deep $0.0127 |
| cfo.ai prompt for Ari (`FEATURE_ARI_PROMPT`) | `test_ari.py` (invented numbers become [___], template fallback) + e2e | this repo: LLM-written, every number from our README, 1 blank |
| /built-with (`VITE_FEATURE_BUILT_WITH`) | `test_built_with.py` + e2e | 97 pushed commits, 41 with Entire checkpoints (entire.io links), 11 improvements linked to commits |
| Integrity checks (`FEATURE_INTEGRITY`, never scored) | `test_integrity.py` (every signal, with false-positive cases) + `python -m evals.integrity`: 9/9 faked fixtures flagged, 9/9 innocent look-alikes cleared ([results](backend/evals/results/2026-10-12-integrity.json)) + e2e | this repo, audit [`7b4b8738ac72`](https://3-82-224-157.sslip.io/a/7b4b8738ac72): 10/10 ok (2 X posts in the window, 71/106 commits matched to pushes after the start, largest commit 18% of lines); sponsor levels unchanged |

Not built: attaching "this verdict is wrong" feedback to the matching neatlogs trace. neatlogs'
Public API has `POST /traces/{traceId}/feedback`, but every feedback write needs a user's OAuth
token (`observability:write`); our project API key is read-only there, and the SDK has no feedback
call ([docs](https://docs.neatlogs.com/api-reference)).

Rollback: `scripts/deploy.sh` keeps the previous image, site and `.env`; `scripts/rollback.sh`
restores them.
