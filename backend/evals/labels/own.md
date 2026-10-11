# DurgaPritam/neatHack-QBITS-: eval label sheet

Repo: <https://github.com/DurgaPritam/neatHack-QBITS-> · audit `92e2d687028e` · phase: deep · run 2026-10-11

Mark each `label:` line as `ok` or `wrong` (optionally `wrong pass` / `wrong fail` with the right verdict, and `-- a note`). A wrong **fail** is a false fail: we penalised something that is there.

## check commits_in_window
**Commits inside the hackathon window**

PreJudge: **pass** — 68 inside, 0 before start, 0 after close; active days: 2026-10-10, 2026-10-11

- look here: <https://github.com/DurgaPritam/neatHack-QBITS-/commits/main>

label: ?

## check neatlogs_sdk
**neatlogs in the dependencies**

PreJudge: **pass** — neatlogs declared as a dependency

- [backend/requirements.txt](https://github.com/DurgaPritam/neatHack-QBITS-/blob/main/backend/requirements.txt)
- look here: <https://github.com/search?q=repo%3ADurgaPritam/neatHack-QBITS-+neatlogs&type=code>

label: ?

## check neatlogs_traces
**neatlogs trace links or screenshots**

PreJudge: **warn** — 3 trace link(s) found, but not publicly viewable: add screenshots or a public share link

- <https://app.neatlogs.com/traces/1458d983f3b529fecc4f3802366a96dc?orgId=c6ad6e53-b608-4914-80dd-1431f37951b6&projectId=91fff568-d321-45b8-83de-035100300128>
- <https://app.neatlogs.com/traces/b044efa9359e61ecef04ed7f61e9e216?orgId=c6ad6e53-b608-4914-80dd-1431f37951b6&projectId=91fff568-d321-45b8-83de-035100300128>
- <https://app.neatlogs.com/traces/c659bf9a4d3ef652dbc334dba40df89c?orgId=c6ad6e53-b608-4914-80dd-1431f37951b6&projectId=91fff568-d321-45b8-83de-035100300128>
- look here: <https://github.com/DurgaPritam/neatHack-QBITS-#readme>

label: ?

## check entire_checkpoints
**Entire checkpoints**

PreJudge: **pass** — 12 commit(s) carry an Entire-Checkpoint trailer; 25 checkpoint ref(s) pushed; README shows 2 checkpoint link(s) and checkpoint ID 01M4NAH03T910P25SNH7F47SQC that matches the repo

- `30b9686d81f5 Entire-Checkpoint: 01M4NF262EAC5M86RACCP3T1G4`
- `a67e64a0cfa8 Entire-Checkpoint: 01M4NE8ENKM0D5PNRFXWB41KV6`
- `88b0282e6cf0 Entire-Checkpoint: 01M4NDRR2C5B0SFTYQVTK0ERYM`
- <https://docs.entire.io/guides/checkpoints/checkpoint-storage>
- <https://entire.io/gh/DurgaPritam/neatHack-QBITS-/commit/72021ab9bde0ea44f40c07637befa7d5228c1180>
- look here: <https://github.com/DurgaPritam/neatHack-QBITS-/commits/main>

label: ?

## check cfo_ai_plan
**cfo.ai plan link**

PreJudge: **pass** — cfo.ai link present; README covers 4/4 of pricing/costs/revenue/runway

- <https://cfo.ai/s/xBCsLLiMtconXUBf>
- `pricing`
- `cost`
- `revenue`
- `runway`
- look here: <https://github.com/DurgaPritam/neatHack-QBITS-#readme>

label: ?

## check demo_video
**Demo video link + length**

PreJudge: **fail** — no YouTube/Loom/Vimeo link in README

- look here: <https://github.com/DurgaPritam/neatHack-QBITS-#readme>

label: ?

## check public_posts
**#neatHack posts**

PreJudge: **warn** — missing links to the posts

- look here: <https://github.com/DurgaPritam/neatHack-QBITS-#readme>

label: ?

## check before_after
**Before/after numbers**

PreJudge: **pass** — before/after comparison with numbers found

- `is in Before → after on openai/swarm: first result in 52s before the two-spee`
- `.md](EVIDENCE.md). Before → after on openai/swarm: first result in 52s before the two-spee`
- `sign, 5.5s after it. | Change`
- look here: <https://github.com/DurgaPritam/neatHack-QBITS-#readme>

label: ?

## check failure_recovery
**Failure + recovery run**

PreJudge: **pass** — failure run described in EVIDENCE.md:81, backed by retry/fallback code

- [EVIDENCE.md:81](https://github.com/DurgaPritam/neatHack-QBITS-/blob/main/EVIDENCE.md#L81)
- [README.md:138](https://github.com/DurgaPritam/neatHack-QBITS-/blob/main/README.md#L138)
- [backend/app/llm.py:35](https://github.com/DurgaPritam/neatHack-QBITS-/blob/main/backend/app/llm.py#L35)
- [backend/app/main.py:124](https://github.com/DurgaPritam/neatHack-QBITS-/blob/main/backend/app/main.py#L124)
- [backend/app/tools/github.py:87](https://github.com/DurgaPritam/neatHack-QBITS-/blob/main/backend/app/tools/github.py#L87)
- look here: <https://github.com/DurgaPritam/neatHack-QBITS-#readme>

label: ?

## claim c1
> Every audit is traced with the neatlogs SDK (backend/app/tracing.py)

PreJudge: **unverified** — No concrete file:line evidence showing import or usage of neatlogs SDK for tracing audits.


label: ?

## claim c2
> Entire is enabled in this repo for Claude Code, and checkpoints are pushed to GitHub as refs/entire/checkpoints/...

PreJudge: **verified** — Code defines checkpoint trailer and fetches refs/entire/checkpoints, confirming the claim.

- [backend/app/tools/github.py:29](https://github.com/DurgaPritam/neatHack-QBITS-/blob/main/backend/app/tools/github.py#L29)

label: ?

## claim c3
> We built the business plan in cfo.ai: shared model · summary in docs/business-plan.md

PreJudge: **unverified** — No docs/business-plan.md or cfo.ai references found in repo.


label: ?

## claim c4
> Quick phase · about 5 s · at most 1 LLM call

PreJudge: **contradicted** — Code states quick phase is ~15 seconds, contradicting the 5‑second claim.

- [backend/app/audit.py:206](https://github.com/DurgaPritam/neatHack-QBITS-/blob/main/backend/app/audit.py#L206)

label: ?

## claim c5
> Links are fetched behind an SSRF guard: _host_problem() in backend/app/tools/links.py refuses any host that resolves to a private, loopback, link-local

PreJudge: **verified** — File explicitly documents SSRF‑safe link checking.

- [backend/app/tools/links.py:3](https://github.com/DurgaPritam/neatHack-QBITS-/blob/main/backend/app/tools/links.py#L3)

label: ?

## claim c6
> The LLM never sets the score. The two things code can't measure (agent quality, usefulness) get an LLM estimate that must cite evidence.

PreJudge: **verified** — Scoring module implements deterministic rubric, confirming claim.

- [backend/app/scoring.py:31](https://github.com/DurgaPritam/neatHack-QBITS-/blob/main/backend/app/scoring.py#L31)

label: ?

## claim c7
> Instructions hidden in a README are detected, flagged on the result page and cannot move the score.

PreJudge: **verified** — Code includes detection of prompt injection in untrusted data.

- [backend/app/tools/rubric.py:632](https://github.com/DurgaPritam/neatHack-QBITS-/blob/main/backend/app/tools/rubric.py#L632)

label: ?

## claim c8
> M2 model + loop changes (openai/swarm) | 40,086 tokens, 106 s, 0 of 8 claims checked, 16 failed LLM calls | 19,066 tokens, 52 s, claims verified with file:line evidence

PreJudge: **unverified** — Repo contains no explicit token or time measurements comparing openai/swarm runs.


label: ?
