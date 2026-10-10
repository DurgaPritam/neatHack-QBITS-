import { defineConfig } from '@playwright/test'

// Runs against a live dev stack: backend in LLM_MODE=replay + `vite`. See e2e/README.md.
export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  expect: { timeout: 30_000 },
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173',
    channel: process.env.E2E_CHANNEL ?? 'chrome',
    acceptDownloads: true,
    screenshot: 'only-on-failure',
  },
})
