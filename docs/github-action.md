# PreJudge GitHub Action

Score your repo against the neatHack rubric on every push. The score, the category breakdown,
progress since the last check and the top 3 fixes land in the job's summary page.

1. Copy [`prejudge.yml`](prejudge.yml) to `.github/workflows/prejudge.yml` in your repo.
2. Push. Open the run under **Actions** and read the summary.

No secrets and no setup: it calls PreJudge's public API with your public repo URL
(`https://github.com/$GITHUB_REPOSITORY`) using `curl` and `jq`, which every Ubuntu runner has.

```
## 🔥 PreJudge: 75/100
Deep check of b2ac135 · full result
| Category | Points |  …
### Top fixes
1. Demo video (<= 3 min, covers all three tools) (+20.0 pts): Record a demo of at most 3 minutes …
```

## Behaviour

- **Never blocks your build.** Rate limited, PreJudge down, or a slow queue: it writes why to the
  summary and exits 0. To fail the job below a score, set `MIN_SCORE` (e.g. `"60"`) in the workflow.
- **Cheap on repeat pushes.** An unchanged commit returns the saved result; new commits get a quick
  audit (~15s). Deep checks are not started by the Action: run one from the result page.
- **Respects the API's limits:** 5 new audits per 10 minutes per IP (GitHub's runners share IPs, so
  a 429 can happen; the summary says so). `concurrency` cancels a superseded run on rapid pushes.
- The job has `contents: read` only and a 5-minute timeout. Nothing from your repo is executed.

Point `PREJUDGE_API` at another deployment to use your own PreJudge.

## Tested

`backend/tests/test_github_action.py` runs the workflow's exact bash step against a stub API
(success, `MIN_SCORE` gate, HTTP 429, API down). The same step was run against production for
this repo before the workflow was enabled here.
