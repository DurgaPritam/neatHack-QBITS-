# Evidence screenshots

neatlogs trace links need a login, so judges see these screenshots instead. Save each one here
under the exact file name, then swap the matching "SCREENSHOT TODO" note in the main README
for the image line next to it:

| File | What to capture | Image line for README.md |
|---|---|---|
| `neatlogs-failure-recovery-29def6e19f64.png` | trace of audit `29def6e19f64`: the 429 on `qwen/qwen3.8-27b` in `llm.verify`, then the calls on `openai/gpt-oss-120b` | `![neatlogs trace: 429 then fallback](evidence/neatlogs-failure-recovery-29def6e19f64.png)` |
| `neatlogs-trace-before-after.png` | an M2 trace (for example `4c5f0f5b9cf9`) next to an M2.5 trace (for example `3c94ce84b8a5`), with tokens and duration visible | `![neatlogs traces before and after](evidence/neatlogs-trace-before-after.png)` |
| `neatlogs-sessions-overview.png` | the sessions list filtered to the `prod` tag | `![neatlogs sessions, prod tag](evidence/neatlogs-sessions-overview.png)` |

PreJudge only counts a screenshot whose file actually exists in the repo.
