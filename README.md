# PreJudge: get roasted before the judges do

Paste a public GitHub repo. An AI judge checks it against the neatHack rubric, verifies README
claims against the code (with file:line evidence), and returns a score, a fix list ordered by
points and a roast. It never runs the audited code. Built for neatHack (Oct 10–12, 2026).

- `backend/`: FastAPI, Groq agent, deterministic scoring, neatlogs tracing (`python -m app.cli <repo_url> --full`)
- `frontend/`: React + Vite + TypeScript UI (see [frontend/README.md](frontend/README.md))
- [EVIDENCE.md](EVIDENCE.md): traces, before/after numbers, throughput, hackathon evidence

## Business plan

PreJudge is bootstrapped, sold as monthly licenses ($199 / $499 / $999) and pay-per-event audits
($49 / $149), with a free tier for individual teams. AI costs $0.0095 per audit (measured in our
traces). In the Main scenario it's profitable every month from Feb 2027, with a 97% gross margin,
and never runs out of cash.

- Summary: [docs/business-plan.md](docs/business-plan.md) (pricing, costs, scenarios, v1 → v3
  changes, risks, hiring rule)
- cfo.ai model: https://cfo.ai/s/xBCsLLiMtconXUBf
