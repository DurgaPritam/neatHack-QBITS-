# Evidence screenshots

neatlogs trace links need a login, so judges see these screenshots instead. All three are embedded
in [README.md](../README.md) and [EVIDENCE.md](../EVIDENCE.md).

| File | What it shows |
|---|---|
| `neatlogs-traces-list.jpeg` | the neatlogs traces list for PreJudge: 5,536 traces captured by Oct 12, 21:35 IST |
| `neatlogs-span-tree.jpeg` | one full deep audit (13 steps, 29.3 s): every agent step and LLM call with model, tokens and cost |
| `neatlogs-failure-recovery.jpeg` | a deep audit (Oct 12, 11:40 IST) where `github.download_tarball`, a `qwen/qwen3.8-27b` call and `agent.search_repo` failed ("Execution Failed") and the agent recovered on `openai/gpt-oss-120b` and other tools |

Checked before committing: no emails, keys or IP addresses in any image. PreJudge only counts a
screenshot whose file exists in the repo, and its integrity check confirms each is a real,
full-size and distinct image.
