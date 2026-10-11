# langchain-ai/open_deep_research: eval label sheet

Repo: <https://github.com/langchain-ai/open_deep_research> · audit `d9ee0299389d` · phase: deep · run 2026-10-11

Mark each `label:` line as `ok` or `wrong` (optionally `wrong pass` / `wrong fail` with the right verdict, and `-- a note`). A wrong **fail** is a false fail: we penalised something that is there.

## check commits_in_window
**Commits inside the hackathon window**

PreJudge: **fail** — 0 inside, 224 before start, 0 after close; active days: none

- `1b7d2e80db9f 2026-08-10T18:13:29Z Bump h2 from 4.3.0 to 4.4.1 in the uv group across 1 directory (#334)`
- `20aaa0d422bd 2026-08-05T08:27:10Z Bump cryptography in the uv group across 1 directory (#331)`
- `7882410280a7 2026-08-05T08:15:27Z Bump aiohttp from 3.14.1 to 3.14.3 in the uv group across 1 directory (#330)`
- look here: <https://github.com/langchain-ai/open_deep_research/commits/main>

label: ?

## check neatlogs_sdk
**neatlogs in the dependencies**

PreJudge: **fail** — no sign of neatlogs in dependencies or README

- look here: <https://github.com/search?q=repo%3Alangchain-ai/open_deep_research+neatlogs&type=code>

label: ?

## check neatlogs_traces
**neatlogs trace links or screenshots**

PreJudge: **fail** — no neatlogs trace links in README (judges expect links or screenshots)

- look here: <https://github.com/langchain-ai/open_deep_research#readme>

label: ?

## check entire_checkpoints
**Entire checkpoints**

PreJudge: **unverified** — couldn't verify automatically: no Entire checkpoints found in commits, refs or the README (not scored)

- look here: <https://github.com/langchain-ai/open_deep_research/commits/main>

label: ?

## check cfo_ai_plan
**cfo.ai plan link**

PreJudge: **fail** — no cfo.ai plan link

- `cost`
- look here: <https://github.com/langchain-ai/open_deep_research#readme>

label: ?

## check demo_video
**Demo video link + length**

PreJudge: **fail** — video is 12:46, over the 3:00 limit

Length read: 12:46 (source: too_long)

- <https://www.youtube.com/watch?v=agGiWUpxkhg>
- look here: <https://github.com/langchain-ai/open_deep_research#readme>

label: ?

## check public_posts
**#neatHack posts**

PreJudge: **fail** — no social posts linked

- look here: <https://github.com/langchain-ai/open_deep_research#readme>

label: ?

## check before_after
**Before/after numbers**

PreJudge: **fail** — no before/after comparison in README

- look here: <https://github.com/langchain-ai/open_deep_research#readme>

label: ?

## check failure_recovery
**Failure + recovery run**

PreJudge: **warn** — the repo handles failures (src/legacy/utils.py:1263) but no run is described

- [src/legacy/utils.py:1263](https://github.com/langchain-ai/open_deep_research/blob/main/src/legacy/utils.py#L1263)
- [src/open_deep_research/deep_researcher.py:635](https://github.com/langchain-ai/open_deep_research/blob/main/src/open_deep_research/deep_researcher.py#L635)
- [src/open_deep_research/utils.py:206](https://github.com/langchain-ai/open_deep_research/blob/main/src/open_deep_research/utils.py#L206)
- look here: <https://github.com/langchain-ai/open_deep_research#readme>

label: ?

## claim c1
> Achieved #6 ranking on the Deep Research Bench Leaderboard with an overall score of 0.4344

PreJudge: **unverified** — No evidence of leaderboard ranking or score found in repo files.


label: ?

## claim c2
> supports a wide range of LLM providers via the init_chat_model() API

PreJudge: **unverified** — init_chat_model is imported, but no concrete evidence of supporting multiple providers such as OpenAI and Anthropic.


label: ?

## claim c3
> Has full MCP compatibility and work native web search for Anthropic and OpenAI

PreJudge: **unverified** — Search finds references to tavily and MCP constants, but no explicit evidence of full MCP compatibility or native web search for Anthropic and OpenAI.


label: ?

## claim c4
> configured for evaluation with Deep Research Bench

PreJudge: **unverified** — run_evaluate.py is present and mentions Deep Research Bench, but no evidence of 100 PhD-level tasks.


label: ?

## claim c5
> Launch agent with the LangGraph server locally

PreJudge: **verified** — README and legacy.md contain command to launch agent with LangGraph server.

- [src/legacy/legacy.md:35-36](https://github.com/langchain-ai/open_deep_research/blob/main/src/legacy/legacy.md#L35-L36)

label: ?

## claim c6
> Added GPT-5 and updated the Deep Research Bench evaluation w/ GPT-5 results

PreJudge: **verified** — Code and README confirm GPT-5 support.

- [tests/run_evaluate.py:25](https://github.com/langchain-ai/open_deep_research/blob/main/tests/run_evaluate.py#L25)

label: ?

## claim c7
> uvx --refresh --from "langgraph-cli[inmem]" --with-editable . --python 3.11 langgraph dev

PreJudge: **verified** — Command explicitly requires Python 3.11.

- [src/legacy/legacy.md:35-36](https://github.com/langchain-ai/open_deep_research/blob/main/src/legacy/legacy.md#L35-L36)

label: ?

## claim c8
> By default it uses the Tavily search API

PreJudge: **unverified** — tavily appears as a dependency, but no clear statement that it is the default search API.


label: ?
