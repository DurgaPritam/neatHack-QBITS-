# PreJudge — Evidence Log

## neatlogs
- Day 1 baseline (M1, deterministic checks only): 17 sessions, 29.4% errors (mostly intentional failure tests)
- Trace 1 — <label>: https://app.neatlogs.com/traces/1458d983f3b529fecc4f3802366a96dc?orgId=c6ad6e53-b608-4914-80dd-1431f37951b6&projectId=91fff568-d321-45b8-83de-035100300128
- Trace 2 — <label>: https://app.neatlogs.com/traces/b044efa9359e61ecef04ed7f61e9e216?orgId=c6ad6e53-b608-4914-80dd-1431f37951b6&projectId=91fff568-d321-45b8-83de-035100300128
- Trace 3 — <label>: https://app.neatlogs.com/traces/c659bf9a4d3ef652dbc334dba40df89c?orgId=c6ad6e53-b608-4914-80dd-1431f37951b6&projectId=91fff568-d321-45b8-83de-035100300128

## Before / after improvements
| Change | Before | After | Trace links |
|---|---|---|---|
| Treat 403 bot-blocked links as "unknown" instead of "dead" | 2 false dead links on openai/swarm | 0 | <add trace link if you have the before and after runs> |
| M2: primary model gpt-oss-120b → qwen3.8-27b (parallel tool calls), 3-turn cap, condensed final answer (openai/swarm) | 40,086 tokens, 106s, verification failed (0/8 claims checked, no estimates), 16 failed LLM calls | 19,066 tokens, 52s, 5/7 claims verified with file:line evidence, estimates cited | neatlogs session = audit id `4c5f0f5b9cf9` (after) |
| README can't verify its own claims (grounding rule) | 3 claims "verified" citing only README.md | 0 circular verifications | — |
| Localhost URLs = unknown, not dead; roast must match results (langchain-ai/open_deep_research) | 5/33 dead links (2 were 127.0.0.1 dev URLs); roast called a live video link "dead" | 3/33 dead; roast accurate | audit ids `53fe70e82c21` (before) → `f2b5f750984e` (after) |
| Moving screen: live step log swapped instead of pushed, fixed-height deep panel that holds the finished result behind "Show the full result", fixed-height example cards, tabular digits (`frontend/e2e/cls.mjs`, Chrome) | Cumulative layout shift: live audit 0.90 desktop / 0.51 mobile; home 0.005 / 0.035 | 0 / 0 on every page and width (home, finished audit, live audit with deep check); no horizontal overflow | e2e asserts CLS < 0.1 |

## M2 full audits (python -m app.cli <repo> --full)
| Repo | Score | Claims verified | Tokens | Time | Audit id |
|---|---|---|---|---|---|
| openai/swarm | 27 | 4/7 | 19,066 | 52s | 4c5f0f5b9cf9 |
| huggingface/smolagents | 17 | 1/8 | 15,061 | 37s | 19605ae23560 |
| langchain-ai/open_deep_research | 32 | 4/8 | 21,172 | 34s | f2b5f750984e |

Failure-recovery evidence: every run above hit Groq 429s (8k TPM free tier) and recovered via
backoff → fallback model → wait-for-quota; each retry/fallback is a step + neatlogs event.

## M2.5: two-speed audits, tarball + search_repo, model rotation (2026-10-10)
Before = M2 single-phase audit. After = quick phase + deep phase, two consecutive runs each
(audit ids are neatlogs session ids; the quick and deep traces share them).

| Repo | Before: tokens / time / verified | After run A: quick → deep, verified | After run B: quick → deep, verified |
|---|---|---|---|
| openai/swarm | 19,066 / 52s / 4 of 7 | 4,094 tok, 5.5s → 16,181 tok, 7.6s · **6 of 8** (`3c94ce84b8a5`) | 4,048 tok, 6.1s → 10,145 tok, 30.6s · 3 of 7 (`4d5dbd1bf972`) |
| huggingface/smolagents | 15,061 / 37s / 1 of 8 | 5,812 tok, 47.5s* → 17,896 tok, 49.8s · **6 of 8** (`b8e64c021d56`) | 3,981 tok, 10.4s → 9,960 tok, 30.3s · 3 of 8 (`fa16370b7b8b`) |
| langchain-ai/open_deep_research | 21,172 / 34s / 4 of 8 | 4,024 tok, 11.9s → 18,159 tok, 57.8s · 3 of 8 (`909e4b969177`) | 4,235 tok, 11.7s → 18,682 tok, 80.8s · 4 of 8 (`6dbfbb5d1c76`) |

\* waited for per-minute quota on every model.

- **Time to first result:** 34–52s → **5.5–12s** (quick phase).
- **Verified claims:** smolagents 1/8 → 3–6/8, swarm 4/7 → 3–6/8, open_deep_research 4/8 → 3–4/8.
  It varies run to run with the model the scheduler gets: under quota pressure the weakest
  model (gpt-oss-20b) does more of the judging.
- **What made the difference** (intermediate runs, same day): with the tarball + `search_repo`
  but no pre-search, smolagents verified **0/8** at 20.8k–23.8k deep tokens, because gpt-oss
  makes one tool call per turn. With **code pre-searching every claim** it verified 4–6/8 at
  10–18k.
- **Quick phase tokens:** the runs above include a roast rewrite. With the quick phase capped
  at one LLM call (`dbec90c`), measured single-call quick audits: swarm 2,154 tok/5.5s,
  smolagents 2,866/7.1s, open_deep_research 2,541/9.6s, pallets/itsdangerous 2,746/8.6s.
- **Demo video duration** is now read from metadata: open_deep_research's demo is **12:46**
  (over the 3:00 limit); before it was reported as "duration not checked".

## Throughput on the Groq free tier (measured 2026-10-10)
Limits are per model (Groq docs + headers): 8,000 tokens/min, 30 req/min, 1,000 req/day,
**200,000 tokens/day**. Rotating 3 tool-calling models gives 24k TPM and 600k tokens/day.

| | Avg tokens | Avg calls | Avg time | Burst (per hour) | Sustained over 24h |
|---|---|---|---|---|---|
| Quick audit | ~2,600 (single call), 3,918 with rewrites | 1–1.7 | 8–14s | **measured 256/h** (10 audits in 141s); TPM bound ≈ 370–550/h | ≈ 9/h (≈ 220/day), TPD-bound |
| Deep audit (one at a time) | 15,170 | 4.5 | 42.8s | ≈ 84/h (latency-bound; TPM bound 95/h) | ≈ 1.6/h (≈ 40/day), TPD-bound |
| Full audit (quick + deep) | ~18,000 | | | | **≈ 31–33/day** |

- The binding limit is **tokens per day**, not tokens per minute. This was demonstrated
  rather than estimated: by the end of the day's development runs, all three models
  answered 429 "tokens per day (TPD): Limit 200000, Used ~199,000", and quick audits fell
  back to template verdicts in 4–9s with each TPD failure recorded as a step
  (`rate_limited_tpd`).
- Reproduce: `python -m scripts.throughput --n 10 --deep-report <--full outputs>`.

## Production (M4, deployed 2026-10-11)
Live at https://3-82-224-157.sslip.io (EC2 t3.small, Docker Compose, Caddy HTTPS). neatlogs
traces from the server carry the `prod` tag.

First production audit of this repo, audit id `29def6e19f64` (LLM_MODE=live):

| phase | time | tokens | result |
|-------|------|--------|--------|
| quick | 5.3 s | 2,173 (1 call, qwen3.8-27b) | 40/100, LLM roast passed the fact check |
| deep  | 40.5 s | 17,232 (5 calls) | 46/100, 6/6 README claims verified |

**Failure + recovery in production:** during the deep check, `llm.verify` on
`qwen/qwen3.8-27b` got a Groq **429 (rate limit)**. The pool backed off and finished the claim
judging on `openai/gpt-oss-120b`: 3 calls, 9,018 prompt tokens. The audit still completed and the
failed call is a recorded step in the audit and in its neatlogs trace (session id `29def6e19f64`).

Smoke test, all passed: quick audit, deep check, card.png (1200×630), `/r/{id}` Open Graph
preview + redirect, Download PNG and Share on X in a real browser, removal → 410 → admin restore,
feedback CSV export, metrics counters, per-IP limit (6th audit in 10 min → 429 with Retry-After),
repo cooldown, nonexistent repo, unknown audit id, CORS rejects other origins, noindex headers,
daily backup written.

### Self-audit before launch (2026-10-11)
PreJudge on its own repo in production, before and after rewriting the README as the submission
page (both runs complete; same code, same rubric):

| | Before (`29def6e19f64`, commit `6ab6239`) | After (`5d7a44233910`, commit `8d76aab`) |
|---|---|---|
| Quick score | 40 | 61 |
| Deep score | 46 | 64 |
| Claims verified | 6 of 6 | 5 of 8 |
| Deep tokens / time | 17,232 / 40.5 s | 24,728 / 67.1 s |

Fixes still open after that run: demo video (+17), #neatHack post links (+3), neatlogs
screenshots (+2.7), Entire checkpoint (+2.1). The run itself hit another production 429 on
`qwen/qwen3.8-27b` in `llm.verify.final` and finished on `openai/gpt-oss-120b` and
`openai/gpt-oss-20b`.

The self-audit also found three PreJudge bugs, now fixed: a re-audit within 10 minutes of a push
returned the stale result (cooldown now compares commits), any neatlogs.com link counted as a
trace, and the before/after check missed numbers in a table.

### Self-audit after the pre-launch fixes (2026-10-11, audit `3b8b2d19878f`, commit `88b0282`)

| | Before (`5d7a44233910`) | After (`3b8b2d19878f`) |
|---|---|---|
| Quick score | 61 | 62 (2,217 tokens, 6.6 s) |
| Deep score | 64 | 64 (16,738 tokens, 39.4 s) |
| Failure + recovery | unverified, half credit | **pass**: run in EVIDENCE.md:81, backed by retry/fallback code and a verified claim |
| Entire checkpoints | none found (not scored) | **pass**: 10 commits with `Entire-Checkpoint` trailers, 25 refs pushed, README ID matches |
| Claims verified | 5 of 8 | 4 of 7 |

Fixes still open: demo video (+20), #neatHack post links (+3), public neatlogs trace screenshots
(+2.7), one dead link (+2: the entire.io checkpoint page, which 404s until the repo is onboarded on
entire.io), README claims evidence (+2.9). The deep phase recovered from an invalid JSON answer in
`verify` (condensed final answer, recorded as `verify.invalid_json`) and the quick roast was rejected
by the fact check once (`quick_verdict.roast_rejected`).

After onboarding the repo on entire.io (mirrored on aws-ap-south-1 and aws-us-east-2), the
checkpoint link opens (HTTP 200) and the self-audit `2b98e8ffae31` (commit `a67e64a`) scores
**64 quick / 68 deep** with 0 dead links and 5 of 8 claims verified (19,858 deep tokens, 40.3 s).
The LLM roast failed the fact check, so a fact-only template roast was used. Fixes left: demo video (+20),
#neatHack posts (+3), neatlogs trace screenshots (+2.7), claim evidence (+3.7).

Other production checks the same day:
- **Demo video length via the YouTube Data API:** re-audit `6c596bffbbb7` of
  langchain-ai/open_deep_research reads **12:46** (`source: youtube_api`) and fails it as over 3:00.
  Before, YouTube blocked yt-dlp on EC2 and the length was unknown.
- **Stored raw errors cleaned:** `python -m app.migrate_friendly --apply` backed up the DB, then
  rewrote 8 fields of audit `fc5068d87579` that still held raw yt-dlp text. 0 raw messages remain.
- **Tracing in tests:** the "failed to export spans" warning came from the neatlogs SDK starting
  its own exporter from `NEATLOGS_API_KEY` in `os.environ` (loaded by dotenv) during tests. Fixed:
  spans only after `init_tracing()`, keys blanked in `conftest.py`, and a test checks that no exporter starts.

## M5 eval set (baseline 2026-10-11)
`python -m evals.run --sheets --tag baseline`: 9 repos (our own, openai/swarm,
huggingface/smolagents, langchain-ai/open_deep_research, and five neatHack submissions anonymised
as Repo A-E), quick + deep phase each, admin reserve, 181k tokens in total. Results:
`backend/evals/results/2026-10-11-baseline.json` (audit ids double as neatlogs session ids, tagged
`test`). Accuracy is reported once the label sheets are marked.

### First labelled repo: langchain-ai/open_deep_research (labels AI-assisted, spot-checked by the team)
The 9 rubric checks were all correct. The claim judge was too strict: 4 false fails out of 8 claims,
and a shell command extracted as a "claim" (a false pass). Fixes, each traced to a labelled error:

1. **Goalpost-moving:** a claim is verified when evidence supports *its own words*; the judge may not
   demand details it doesn't state ("100 PhD-level tasks").
2. **Config files:** presearch always shows config/settings hits first (`configuration.py`, `*.toml`,
   `*.yaml`, enums); a default value, enum option or config class is direct evidence for "by default
   uses X" / "supports X".
3. **Claim extraction:** shell commands, install steps and code are skipped (prompt + a code filter).
   Found while re-running: the extractor padded claims with details from the next README sentence
   ("…which has 100 PhD-level tasks"), so a paraphrase may not add numbers its quote lacks, and a
   quote stitched across sentences with "…" keeps only its first sentence.
4. **No README as proof** in verdict text (prompt + a sanitizer that drops such sentences).
5. **No stray evidence bullets** like "cost" on the cfo.ai check.

| Run (audit id = neatlogs session) | Fixes in place | Rubric checks | Claims correct | Claim false fails | Claim false passes |
|---|---|---|---|---|---|
| Baseline `d9ee0299389d` | none | 9/9 | 3/8 (37.5%) | 4 | 1 |
| After 1 `e166d6c4a643` | 1–5 (prompts, config presearch, command filter) | 9/9 | 6/6 (100%) | 0 | 0 |
| After 2 `55cddb3e68c6` | same | 9/9 | 7/8 (87.5%) | 1 | 0 |
| After 3 `da5768158590` | + config hits for every claim | 9/9 | 5/6 (83.3%) | 1 | 0 |
| After 4 `c31e614f93da` | + no numbers the quote lacks | 9/9 | 4/5 (80%) | 1 | 0 |
| After 5 `26d849e7c7aa` | + stitched quotes cut | 9/9 | 5/5 (100%) | 0 | 0 |

Caveats, stated plainly: one labelled repo (8 claims), so these are small numbers. Claims are
re-extracted every run, so 0-3 labelled claims per run weren't extracted again and aren't scored. The
remaining false fails in runs 2-4 were all the padded "Deep Research Bench" claim, the error that the
last two fixes target. A further confirmation run was blocked by the day's Groq budget and is next.

## Entire
- Enabled 2026-10-11 for Claude Code, ref-based storage (`refs/entire/checkpoints/<shard>/<id>`),
  synced to `origin`.
- First checkpoint: ID `01M4NAH03T910P25SNH7F47SQC`, trailer on commit `72021ab`:
  https://entire.io/gh/DurgaPritam/neatHack-QBITS-/commit/72021ab9bde0ea44f40c07637befa7d5228c1180
- Imported history: 2 earlier Claude Code sessions (15 turns) with `entire import claude-code
  --session ...`. Before importing, the transcripts were scanned for the repo's secrets. One
  session held API keys pasted in a prompt, so a local (gitignored) Entire redaction pack was
  added first. All checkpoint blobs were then rescanned before pushing: 0 secret matches.
- Pre-publication scan: every blob in the git history plus all Entire checkpoint data, checked
  against the exact `.env` values and common key patterns. 0 real secrets. The only hits were an
  empty `GITHUB_TOKEN=` line in `.env.example` and GitHub's own expired S3 presigned image URL in a
  recorded audit fixture.

## cfo.ai
- Shared model (final, v3): https://cfo.ai/s/xBCsLLiMtconXUBf
- Plan summary: [docs/business-plan.md](docs/business-plan.md) · Ari's raw summary:
  [docs/cfo-ai-notes-raw.md](docs/cfo-ai-notes-raw.md)
- Screenshots / model export: _to add_ (`evidence/cfo-*.png`, `docs/cfo-ai-model.*`)

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

- **v1 → v2:** added size-agnostic $49 events and a 500-audit free tier, removed the raise to
  test bootstrapping. That exposed a cash gap at launch: the $0.40 AI guess and a $300 hosting
  guess.
- **v2 → v3:** replaced the guesses with this project's measurements. Our traces put AI at
  $0.005 quick and $0.02 deep, $0.0095 blended, about 42× below the guess; hosting is $20/mo.
  That moved break-even 9 months earlier. Size-based event pricing also raised revenue per event
  by about 80%.
- **Final v3 starting cash is $500** (it replaced the $2,000 placeholder). Main still never runs out:
  lowest cash is $248 in Jan 2027, profitable every month from Feb 2027, $88,022 by Sep 2028.

## Building in public (#neatHack)
- Launch thread on X (#neatHack): https://x.com/PritamLite/status/2109287438342582620