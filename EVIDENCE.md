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

## M2 full audits (python -m app.cli <repo> --full)
| Repo | Score | Claims verified | Tokens | Time | Audit id |
|---|---|---|---|---|---|
| openai/swarm | 27 | 4/7 | 19,066 | 52s | 4c5f0f5b9cf9 |
| huggingface/smolagents | 17 | 1/8 | 15,061 | 37s | 19605ae23560 |
| langchain-ai/open_deep_research | 32 | 4/8 | 21,172 | 34s | f2b5f750984e |

Failure-recovery evidence: every run above hit Groq 429s (8k TPM free tier) and recovered via
backoff → fallback model → wait-for-quota; each retry/fallback is a step + neatlogs event.

## Entire
- Checkpoint link + ID: <paste>

## cfo.ai
- Business plan: <paste link>

## Building in public (#neatHack)
- <post links>