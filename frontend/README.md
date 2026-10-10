# PreJudge frontend

React + Vite + TypeScript, plain CSS. Talks to the FastAPI backend in `../backend`.

```bash
npm install
npm run dev          # http://localhost:5173, proxies /api and /r to the backend
```

The dev proxy targets `http://localhost:8000`; set `VITE_BACKEND=http://localhost:8010` (etc.)
to point it elsewhere. Run the backend with `LLM_MODE=replay` to use saved LLM responses
instead of spending Groq tokens.

Pages:
- `/` — repo URL input, live "N repos roasted" counter, budget banner, 3 saved examples
- `/a/:id` — live step log (polls every 1.5s), quick result, "Run deep check" with queue
  position/ETA, full result (score + categories, roast, best thing, fixes, claims with
  evidence, per-check feedback), roast card PNG download and Share on X (`/r/:id` link)

Optional build-time settings: `VITE_SHARE_BASE` (origin for `/r/:id` share links, defaults to
the page origin), `VITE_SITE_NAME` (shown on the roast card, defaults to the host).

## End-to-end tests

```bash
./e2e/run.sh         # fresh replay-mode backend + Vite + Playwright (uses installed Chrome)
```

No LLM tokens are spent; GitHub calls are live. Screenshots land in `e2e-shots/`.
