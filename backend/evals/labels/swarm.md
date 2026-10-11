# openai/swarm: eval label sheet

Repo: <https://github.com/openai/swarm> · audit `84fa4f9fefd5` · phase: deep · run 2026-10-11

Mark each `label:` line as `ok` or `wrong` (optionally `wrong pass` / `wrong fail` with the right verdict, and `-- a note`). A wrong **fail** is a false fail: we penalised something that is there.

## check commits_in_window
**Commits inside the hackathon window**

PreJudge: **fail** — 0 inside, 29 before start, 0 after close; active days: none

- `6af0b4caf37d 2026-04-15T17:10:28Z Pin pre-commit hook revisions to immutable commits (#83)`
- `0c82d7d868bb 2025-03-11T17:27:22Z update readme`
- `b186492333e5 2025-03-11T17:22:35Z update pointer to Agents SDK`
- look here: <https://github.com/openai/swarm/commits/main>

label: ?

## check neatlogs_sdk
**neatlogs in the dependencies**

PreJudge: **fail** — no sign of neatlogs in dependencies or README

- look here: <https://github.com/search?q=repo%3Aopenai/swarm+neatlogs&type=code>

label: ?

## check neatlogs_traces
**neatlogs trace links or screenshots**

PreJudge: **fail** — no neatlogs trace links in README (judges expect links or screenshots)

- look here: <https://github.com/openai/swarm#readme>

label: ?

## check entire_checkpoints
**Entire checkpoints**

PreJudge: **unverified** — couldn't verify automatically: no Entire checkpoints found in commits, refs or the README (not scored)

- look here: <https://github.com/openai/swarm/commits/main>

label: ?

## check cfo_ai_plan
**cfo.ai plan link**

PreJudge: **fail** — no cfo.ai plan link

- look here: <https://github.com/openai/swarm#readme>

label: ?

## check demo_video
**Demo video link + length**

PreJudge: **fail** — no YouTube/Loom/Vimeo link in README

- look here: <https://github.com/openai/swarm#readme>

label: ?

## check public_posts
**#neatHack posts**

PreJudge: **fail** — no social posts linked

- look here: <https://github.com/openai/swarm#readme>

label: ?

## check before_after
**Before/after numbers**

PreJudge: **fail** — no before/after comparison in README

- look here: <https://github.com/openai/swarm#readme>

label: ?

## check failure_recovery
**Failure + recovery run**

PreJudge: **warn** — failure run described in README.md:226, but no trace link, screenshot, log or retry/fallback code backs it

- [README.md:226](https://github.com/openai/swarm/blob/main/README.md#L226)
- look here: <https://github.com/openai/swarm#readme>

label: ?

## claim c1
> Requires Python 3.10+

PreJudge: **verified** — The setup.cfg file explicitly declares the Python version requirement as >=3.10.

- [setup.cfg:22](https://github.com/openai/swarm/blob/main/setup.cfg#L22)

label: ?

## claim c2
> If `True`, enables streaming responses

PreJudge: **verified** — The core.py file contains a 'stream' parameter and a 'run_and_stream' method, confirming streaming support.

- [swarm/core.py:38](https://github.com/openai/swarm/blob/main/swarm/core.py#L38)
- [swarm/core.py:139](https://github.com/openai/swarm/blob/main/swarm/core.py#L139)

label: ?

## claim c3
> can at any point choose to hand off a conversation to another `Agent`

PreJudge: **verified** — The test file contains a specific test for handoffs and a function named 'transfer_to_agent2', confirming the feature exists.

- [tests/test_core.py:118](https://github.com/openai/swarm/blob/main/tests/test_core.py#L118)
- [tests/test_core.py:119](https://github.com/openai/swarm/blob/main/tests/test_core.py#L119)

label: ?

## claim c4
> does not store state between calls

PreJudge: **verified** — The project description in setup.cfg and the README both explicitly state that the system is stateless and does not store state between calls.

- [setup.cfg:5](https://github.com/openai/swarm/blob/main/setup.cfg#L5)

label: ?

## claim c5
> context_variables

PreJudge: **verified** — The core.py file defines a constant for context variables and accepts them as a dictionary parameter in the get_chat_completion method.

- [swarm/core.py:23](https://github.com/openai/swarm/blob/main/swarm/core.py#L23)
- [swarm/core.py:36](https://github.com/openai/swarm/blob/main/swarm/core.py#L36)

label: ?

## claim c6
> Swarm is now replaced by the OpenAI Agents SDK

PreJudge: **unverified** — The search for 'experimental', 'educational', or 'not production' returned only irrelevant matches in JSON log files and data files. There is no direct evidence in the code or primary documentation (README/setup.cfg) explicitly labeling the


label: ?
