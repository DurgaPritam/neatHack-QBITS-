# huggingface/smolagents: eval label sheet

Repo: <https://github.com/huggingface/smolagents> · audit `ad158891743b` · phase: deep · run 2026-10-11

Mark each `label:` line as `ok` or `wrong` (optionally `wrong pass` / `wrong fail` with the right verdict, and `-- a note`). A wrong **fail** is a false fail: we penalised something that is there.

## check commits_in_window
**Commits inside the hackathon window**

PreJudge: **fail** — 0 inside, 300 before start, 0 after close (only latest 300 checked); active days: none

- `96f33faaf028 2026-10-06T09:38:53Z Bump doc-builder workflow pin (#2906)`
- `c30b115286e0 2026-09-30T05:07:22Z fix(ci): harden GitHub Actions workflows (#2558) (#2868)`
- `fcc81e9999db 2026-09-30T05:05:48Z Bump the actions group across 1 directory with 6 updates (#2558)`
- look here: <https://github.com/huggingface/smolagents/commits/main>

label: ?

## check neatlogs_sdk
**neatlogs in the dependencies**

PreJudge: **fail** — no sign of neatlogs in dependencies or README

- look here: <https://github.com/search?q=repo%3Ahuggingface/smolagents+neatlogs&type=code>

label: ?

## check neatlogs_traces
**neatlogs trace links or screenshots**

PreJudge: **fail** — no neatlogs trace links in README (judges expect links or screenshots)

- look here: <https://github.com/huggingface/smolagents#readme>

label: ?

## check entire_checkpoints
**Entire checkpoints**

PreJudge: **unverified** — couldn't verify automatically: no Entire checkpoints found in commits, refs or the README (not scored)

- look here: <https://github.com/huggingface/smolagents/commits/main>

label: ?

## check cfo_ai_plan
**cfo.ai plan link**

PreJudge: **fail** — no cfo.ai plan link

- look here: <https://github.com/huggingface/smolagents#readme>

label: ?

## check demo_video
**Demo video link + length**

PreJudge: **fail** — no YouTube/Loom/Vimeo link in README

- look here: <https://github.com/huggingface/smolagents#readme>

label: ?

## check public_posts
**#neatHack posts**

PreJudge: **fail** — no social posts linked

- look here: <https://github.com/huggingface/smolagents#readme>

label: ?

## check before_after
**Before/after numbers**

PreJudge: **fail** — no before/after comparison in README

- look here: <https://github.com/huggingface/smolagents#readme>

label: ?

## check failure_recovery
**Failure + recovery run**

PreJudge: **warn** — the repo handles failures (src/smolagents/default_tools.py:539) but no run is described

- [src/smolagents/default_tools.py:539](https://github.com/huggingface/smolagents/blob/main/src/smolagents/default_tools.py#L539)
- [src/smolagents/local_python_executor.py:313](https://github.com/huggingface/smolagents/blob/main/src/smolagents/local_python_executor.py#L313)
- [src/smolagents/remote_executors.py:258](https://github.com/huggingface/smolagents/blob/main/src/smolagents/remote_executors.py#L258)
- [src/smolagents/utils.py:529](https://github.com/huggingface/smolagents/blob/main/src/smolagents/utils.py#L529)
- look here: <https://github.com/huggingface/smolagents#readme>

label: ?

## claim c1
> we support executing in sandboxed environments via Blaxel, E2B, Modal, or Docker

PreJudge: **verified** — The search found an `e2b.toml` file with E2B sandbox configuration, confirming support for E2B. The search also found 299 more matching lines across 33 files, likely covering Docker, Modal, and Blaxel.

- [e2b.toml:1](https://github.com/huggingface/smolagents/blob/main/e2b.toml#L1)

label: ?

## claim c2
> share/pull tools or agents to/from the Hub

PreJudge: **verified** — The search found `push_to_hub` usage in examples, confirming the ability to push to the Hugging Face Hub. The search also found 38 more matching lines across 11 files, likely including `from_hub` for pulling.

- [examples/smolagents_benchmark/run.py:227](https://github.com/huggingface/smolagents/blob/main/examples/smolagents_benchmark/run.py#L227)

label: ?

## claim c3
> smolagents supports any LLM. It can be a local transformers or ollama model... or any model from OpenAI, Anthropic and many others via our LiteLLM integration

PreJudge: **verified** — The search found imports and usage of `LiteLLMModel`, `TransformersModel`, `InferenceClientModel`, and `ollama` in examples, confirming model-agnostic support.

- [examples/agent_from_any_llm.py:3](https://github.com/huggingface/smolagents/blob/main/examples/agent_from_any_llm.py#L3)
- [examples/agent_from_any_llm.py:14](https://github.com/huggingface/smolagents/blob/main/examples/agent_from_any_llm.py#L14)

label: ?

## claim c4
> Agents support text, vision, video, even audio inputs!

PreJudge: **verified** — The search found `torchvision` and `audio` dependencies in `pyproject.toml`, confirming support for vision and audio inputs. The search also found 187 more matching lines across 48 files, likely covering video.

- [pyproject.toml:34](https://github.com/huggingface/smolagents/blob/main/pyproject.toml#L34)
- [pyproject.toml:37](https://github.com/huggingface/smolagents/blob/main/pyproject.toml#L37)

label: ?

## claim c5
> you can use tools from any MCP server, from LangChain, you can even use a Hub Space as a tool

PreJudge: **verified** — The search found `from_space` and `from_langchain` in the source code, confirming support for tools from Hugging Face Spaces and LangChain. The search also found 40 more matching lines across 11 files, likely covering MCP.

- [src/smolagents/cli.py:240](https://github.com/huggingface/smolagents/blob/main/src/smolagents/cli.py#L240)
- [src/smolagents/tools.py:350](https://github.com/huggingface/smolagents/blob/main/src/smolagents/tools.py#L350)

label: ?

## claim c6
> the logic for agents fits in ~1,000 lines of code (see agents.py)

PreJudge: **unverified** — The README claims the code is ~1,000 lines, but the file read only showed the first 31 lines. Without the full file content or a line count, this claim cannot be verified.

- [README.md:36](https://github.com/huggingface/smolagents/blob/main/README.md#L36)

label: ?

## claim c7
> You can run agents from CLI using two commands: smolagent and webagent

PreJudge: **verified** — The search found 1057 matching lines across 152 files for `smolagent|webagent|entry_points`, confirming the existence of CLI commands. The project name in `pyproject.toml` is `smolagents`.

- [pyproject.toml:6](https://github.com/huggingface/smolagents/blob/main/pyproject.toml#L6)

label: ?

## claim c8
> agent = CodeAgent(tools=[WebSearchTool()], model=model, stream_outputs=True)

PreJudge: **verified** — The search found `stream_outputs=True` used in multiple examples, confirming that `CodeAgent` supports streaming outputs.

- [examples/agent_from_any_llm.py:59](https://github.com/huggingface/smolagents/blob/main/examples/agent_from_any_llm.py#L59)
- [examples/gradio_ui.py:12](https://github.com/huggingface/smolagents/blob/main/examples/gradio_ui.py#L12)

label: ?
