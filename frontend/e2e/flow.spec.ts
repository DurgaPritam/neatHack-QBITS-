import { expect, test, type Page } from '@playwright/test'

// Full flow against the real backend in LLM_MODE=replay (no LLM tokens). GitHub is live.
const SHOTS = process.env.E2E_SHOTS ?? 'e2e-shots'

// Cumulative layout shift, counted from page load (shifts right after a click or key press don't count).
async function watchLayoutShift(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __cls: number }
    w.__cls = 0
    new PerformanceObserver((list) => {
      for (const e of list.getEntries() as unknown as { value: number; hadRecentInput: boolean }[])
        if (!e.hadRecentInput) w.__cls += e.value
    }).observe({ type: 'layout-shift', buffered: true })
  })
}
const layoutShift = (page: Page) => page.evaluate(() => (window as unknown as { __cls: number }).__cls)

async function shot(page: Page, name: string) {
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true })
}

test('home: headline, live counter, three saved examples', async ({ page }) => {
  await watchLayoutShift(page)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Get roasted before the judges do' })).toBeVisible()
  await expect(page.getByTestId('counter')).toHaveText(/^\d+ roasts?$/)
  await expect(page.getByTestId('example')).toHaveCount(3)
  await page.waitForTimeout(1000)
  expect(await layoutShift(page)).toBeLessThan(0.1)
  await expect(page.getByTestId('deadline')).toHaveCount(0)              // countdown removed
  await shot(page, 'home-desktop')
  await page.setViewportSize({ width: 390, height: 844 })
  await shot(page, 'home-mobile')
})

test('a roast that failed the fact check is labelled fact-only', async ({ page }) => {
  await page.goto('/a/4d5dbd1bf972') // openai/swarm example: its jokes were rejected in the real run
  await expect(page.getByTestId('fact-only')).toContainText("didn't pass our fact check")
})

test('invalid URL is caught before calling the API', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('GitHub repo URL').fill('not a repo')
  await page.getByRole('button', { name: 'Roast my repo' }).click()
  await expect(page.getByRole('alert')).toContainText('Paste a public GitHub repo')
  await expect(page).toHaveURL('/')
})

test('saved example: score, categories, roast, fixes, claims with evidence, feedback, card', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('example').filter({ hasText: 'open_deep_research' }).click()
  await expect(page.getByTestId('score')).toContainText('18')
  await expect(page.getByTestId('deep-badge')).toHaveText('Deep check complete')
  await expect(page.locator('.tag-estimated')).toHaveCount(2) // agent + usefulness
  await expect(page.getByTestId('estimate-badge')).toContainText('estimated by the AI')
  await expect(page.getByTestId('roast')).toContainText('12:46')
  await expect(page.getByText('Best thing about this repo')).toBeVisible()

  const pts = await page.locator('.fix-pts').allInnerTexts()
  const nums = pts.map((p) => parseFloat(p.replace('+', '')))
  expect(nums).toEqual([...nums].sort((a, b) => b - a))

  const evidence = page.locator('.claims .evidence a').first()
  await expect(evidence).toHaveAttribute('href', /^https:\/\/github\.com\/langchain-ai\/open_deep_research\/blob\/main\/.+#L\d+/)

  const firstCheck = page.locator('.check').first()
  await firstCheck.getByRole('button', { name: 'This verdict is wrong' }).click()
  await firstCheck.getByPlaceholder("What's wrong? (optional)").fill('e2e test')
  await firstCheck.getByRole('button', { name: 'Send' }).click()
  await expect(firstCheck.getByText('Thanks, noted.')).toBeVisible()

  const x = page.getByRole('link', { name: 'Share on X' })
  const href = decodeURIComponent((await x.getAttribute('href')) ?? '')
  expect(href).toContain('twitter.com/intent/tweet')
  expect(href).toMatch(/\/r\/6dbfbb5d1c76/)
  expect(href).toContain('#neatHack')

  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Download PNG' }).click(),
  ])
  expect(download.suggestedFilename()).toBe('prejudge-langchain-ai-open_deep_research.png')
  await download.saveAs(`${SHOTS}/downloaded-card.png`)
  await shot(page, 'example-result')
  await page.setViewportSize({ width: 390, height: 844 })
  await shot(page, 'example-result-mobile')
})

test('new audit: live log, quick result, deep check with queue, deep badge', async ({ page }) => {
  await watchLayoutShift(page)
  await page.goto('/')
  await page.getByLabel('GitHub repo URL').fill('https://github.com/openai/swarm')
  await page.getByRole('button', { name: 'Roast my repo' }).click()
  await expect(page).toHaveURL(/\/a\/[0-9a-f]{12}$/)
  await expect(page.getByText('Opening the repo')).toBeVisible()
  await expect(page.getByTestId('score')).toBeVisible()
  await expect(page.getByText('Quick check', { exact: true })).toBeVisible()
  await expect(page.getByTestId('roast')).not.toBeEmpty()
  await shot(page, 'new-quick')

  await page.getByRole('button', { name: 'Run deep check' }).click()
  await expect(page.getByTestId('deep-status')).toBeVisible()
  await shot(page, 'new-deep-queued')
  // the finished deep check waits behind a button instead of reflowing the page under the reader
  await expect(page.getByTestId('deep-ready')).toContainText('Deep check done', { timeout: 60_000 })
  await page.getByRole('button', { name: 'Show the full result' }).click()
  await expect(page.getByTestId('deep-badge')).toHaveText('Deep check complete')
  await expect(page.locator('.claims .claim').first()).toBeVisible()
  await expect(page.locator('.steplog').getByText('Pulling claims out of the README')).toBeVisible()
  await expect(page.getByTestId('deep-done')).toContainText('Deep check complete')  // the panel stays put
  expect(await layoutShift(page)).toBeLessThan(0.1)       // the page doesn't jump as results arrive
  await shot(page, 'new-deep-done')
})

test('repo without a fixture in replay mode: honest quick-facts label', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('GitHub repo URL').fill('https://github.com/pallets/click')
  await page.getByRole('button', { name: 'Roast my repo' }).click()
  await expect(page.getByTestId('template-notice')).toContainText('Quick facts mode: the roast oven is cooling')
  await expect(page.getByTestId('estimate-badge')).toContainText('neutral placeholders until the deep check')
  await expect(page.getByTestId('roast-card')).toContainText('quick facts mode')
  await shot(page, 'template-mode')
})

test('repo that does not exist', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('GitHub repo URL').fill('https://github.com/DurgaPritam/no-such-repo-prejudge-e2e')
  await page.getByRole('button', { name: 'Roast my repo' }).click()
  await expect(page.getByTestId('repo-unavailable')).toContainText("We can't find this repo.")
  await expect(page.getByRole('button', { name: 'Run deep check' })).toHaveCount(0)
  await shot(page, 'not-found')
})

test('private repo state (GitHub said private)', async ({ page }) => {
  // A real private repo can't be fetched anonymously; reuse a saved example's shape with a private gate.
  await page.route('**/api/audits/privatetest01', async (route) => {
    const ex = await (await page.request.get('/api/audits/4d5dbd1bf972')).json()
    ex.id = 'privatetest01'
    ex.result.score.gated = true
    ex.result.checks = [{ id: 'repo_public', title: 'Repo is public', status: 'fail', category: 'eligibility',
      detail: "repo is private; judges can't see it", evidence: [] }]
    ex.steps = [{ name: 'github.get_repo', status: 'failed', error_kind: 'private', detail: '', duration_ms: 1 }]
    await route.fulfill({ json: ex })
  })
  await page.goto('/a/privatetest01')
  await expect(page.getByTestId('repo-unavailable')).toContainText('This repo is private.')
})

test('deep check request fails on network error', async ({ page }) => {
  await page.route('**/api/audits/quicktest01', async (route) => {
    const ex = await (await page.request.get('/api/audits/4d5dbd1bf972')).json()
    Object.assign(ex, { id: 'quicktest01', status: 'quick_ready', phases: { quick: 'done', deep: 'available' } })
    ex.result.phase = 'quick'
    await route.fulfill({ json: ex })
  })
  await page.route('**/api/audits/quicktest01/deep', (route) => route.abort('internetdisconnected'))
  await page.goto('/a/quicktest01')
  await expect(page.getByText('Quick check', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Run deep check' }).click()
  await expect(page.getByText("Can't reach PreJudge. Try again?")).toBeVisible()
})

test('lost connection while on an audit page', async ({ page }) => {
  await page.route('**/api/audits/*', (route) => route.abort('internetdisconnected'))
  await page.goto('/a/4d5dbd1bf972')
  await expect(page.getByTestId('offline')).toContainText('Lost connection to PreJudge')
  await page.unroute('**/api/audits/*')
  await page.getByRole('button', { name: 'Retry now' }).click()
  await expect(page.getByTestId('score')).toBeVisible()
  await expect(page.getByTestId('offline')).toHaveCount(0)
})

test('home when the API is down', async ({ page }) => {
  await page.route('**/api/**', (route) => route.abort('internetdisconnected'))
  await page.goto('/')
  await expect(page.getByTestId('counter')).toContainText("Can't reach the server")
  await page.getByLabel('GitHub repo URL').fill('https://github.com/openai/swarm')
  await page.getByRole('button', { name: 'Roast my repo' }).click()
  await expect(page.getByRole('alert')).toContainText("Can't reach PreJudge right now")
})

test('busy and cooling banners', async ({ page }) => {
  for (const [state, text] of [['busy', 'Busy right now'], ['cooling', 'The roast oven is cooling']] as const) {
    await page.route('**/api/stats', (route) =>
      route.fulfill({ json: { total_audits: 3, completed_audits: 3, budget_state: state, deep_queue: 6, deep_wait_s: 420, llm_mode: 'replay' } }))
    await page.goto('/')
    await expect(page.getByTestId('budget-banner')).toContainText(text)
    await page.unroute('**/api/stats')
  }
})

test('unknown audit id', async ({ page }) => {
  await page.goto('/a/doesnotexist')
  await expect(page.getByRole('heading', { name: 'No such audit.' })).toBeVisible()
})

test('share page has Open Graph card and redirects to the audit', async ({ page, request }) => {
  const html = await (await request.get('/r/6dbfbb5d1c76', { maxRedirects: 0 })).text()
  expect(html).toContain('og:image')
  expect(html).toContain('/api/audits/6dbfbb5d1c76/card.png')
  expect(html).toContain('summary_large_image')
  const png = await request.get('/api/audits/6dbfbb5d1c76/card.png')
  expect(png.headers()['content-type']).toBe('image/png')
  await page.goto('/r/6dbfbb5d1c76')
  await expect(page).toHaveURL(/\/a\/6dbfbb5d1c76$/)
  await expect(page.getByTestId('score')).toBeVisible()
})

test('request removal hides the audit, its card and share page', async ({ page, request }) => {
  // the not-found audit from above is a real audit row we can safely remove
  const { id } = await (await request.post('/api/audits', {
    data: { repo_url: 'https://github.com/DurgaPritam/no-such-repo-prejudge-e2e' },
  })).json()
  await page.goto(`/a/${id}`)
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', 'noindex, nofollow')
  await page.getByTestId('request-removal').click()
  await page.getByLabel('Reason for removal (optional)').fill('e2e test')
  await page.getByRole('button', { name: 'Remove it' }).click()
  await expect(page.getByTestId('audit-removed')).toBeVisible()
  await shot(page, 'removed')
  await page.reload()
  await expect(page.getByTestId('audit-removed')).toBeVisible()
  expect((await request.get(`/api/audits/${id}/card.png`)).status()).toBe(410)
  expect((await request.get(`/r/${id}`, { maxRedirects: 0 })).status()).toBe(410)
})

test('re-check of the same commit: reuse notice, progress delta, percentiles, card delta', async ({ page }) => {
  // A saved example, with the M6 fields the API adds on a re-check (no new commits, +22, a cohort).
  await page.route('**/api/audits/6dbfbb5d1c76', async (route) => {
    const res = await route.fetch()
    const body = await res.json()
    body.result.reuse = { from: 'aaaaaaaaaaaa', checked_at: new Date(Date.now() - 3 * 3600e3).toISOString(),
                          tokens_saved: 18159, deep: false }
    body.result.progress = { previous_audit_id: 'aaaaaaaaaaaa', previous_at: '2026-10-11T08:00:00+00:00',
                             previous_score: 46, score: 68, delta: 22, text: '+22 since your last check (46 → 68)',
                             fixed: ['Demo video (<= 3 min)', 'cfo.ai business plan'], regressed: [] }
    body.percentiles = { cohort_size: 18, beats_pct: 62, text: "Your score beats 62% of neatHack repos we've checked",
                         checks: [{ check_id: 'demo_video', pct: 34, passed: true,
                                    text: "Only 34% of teams have a demo video under 3:00. You're one of them ✅" },
                                  { check_id: 'cfo_ai_plan', pct: 55, passed: false,
                                    text: '55% of teams already have a cfo.ai business plan.' }] }
    await route.fulfill({ response: res, json: body })
  })
  await page.goto('/a/6dbfbb5d1c76')
  await expect(page.getByTestId('reuse-notice')).toHaveText(
    "No new commits since your last check 3 hours ago, so here's that result. Push your fixes and check again.")
  await expect(page.getByTestId('progress')).toContainText('+22 since your last check (46 → 68)')
  await expect(page.getByTestId('progress')).toContainText('Fixed: Demo video (<= 3 min), cfo.ai business plan')
  await expect(page.getByTestId('percentiles')).toContainText("Your score beats 62% of neatHack repos we've checked")
  await expect(page.getByTestId('percentiles')).toContainText("Only 34% of teams have a demo video under 3:00. You're one of them ✅")
  await expect(page.getByTestId('card-delta')).toHaveText('+22 since last check')
  await shot(page, 'm6-history')
})

test('step log numbers repeated steps instead of repeating identical lines', async ({ page }) => {
  await page.goto('/a/6dbfbb5d1c76')
  const labels = await page.locator('.steplog .step-label').allInnerTexts()
  expect(labels.some((l) => /^Judging claims, round 1 of \d+$/.test(l)) || labels.every((l) => !l.startsWith('Judging claims'))).toBe(true)
  const dupes = labels.filter((l, i) => labels.indexOf(l) !== i)
  expect(dupes).toEqual([])
})

test('admin page: token kept in memory, overview tables', async ({ page }) => {
  await page.goto('/admin')
  await expect(page.getByTestId('admin-login')).toBeVisible()
  await page.getByLabel('Admin token').fill('wrong')
  await page.getByRole('button', { name: 'Open' }).click()
  await expect(page.getByText('That token was rejected.')).toBeVisible()
  await page.getByLabel('Admin token').fill('e2e-admin')
  await page.getByRole('button', { name: 'Open' }).click()
  await expect(page.getByTestId('admin')).toBeVisible()
  await expect(page.getByText('Deep checks today')).toBeVisible()
  await expect(page.getByText('Tokens saved by reuse')).toBeVisible()
  await expect(page.getByRole('heading', { name: /Projects/ })).toBeVisible()
  await expect(page.getByTestId('admin-unique')).toHaveText(/\d+ visible roasts · \d+ unique repos/)  // admin keeps it
  expect(await page.evaluate(() => JSON.stringify(localStorage) + JSON.stringify(sessionStorage) + document.cookie))
    .not.toContain('e2e-admin')
  await shot(page, 'm6-admin')
  await page.reload()
  await expect(page.getByTestId('admin-login')).toBeVisible() // forgotten on reload
})

test('"Show my roast on the homepage": off by default, opted-in roast leads the feed', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('[data-example="opted-in"]')).toHaveCount(0)
  await page.getByLabel('GitHub repo URL').fill('https://github.com/openai/swarm')
  await page.getByRole('button', { name: 'Roast my repo' }).click()
  const box = page.getByTestId('showcase-toggle').getByRole('checkbox')
  await expect(box).not.toBeChecked()
  await box.check()
  await expect(box).toBeChecked()
  const id = page.url().split('/a/')[1]
  await watchLayoutShift(page)
  await page.goto('/')
  const first = page.getByTestId('example').first()
  await expect(first).toHaveAttribute('data-example', 'opted-in')
  await expect(first).toHaveAttribute('href', `/a/${id}`)
  await expect(page.getByTestId('example')).toHaveCount(3)          // topped up with built-in examples
  await page.waitForTimeout(1000)
  expect(await layoutShift(page)).toBeLessThan(0.1)
  await page.goto(`/a/${id}`)
  await page.getByTestId('showcase-toggle').getByRole('checkbox').uncheck()   // and back off
  await page.goto('/')
  await expect(page.locator('[data-example="opted-in"]')).toHaveCount(0)
})

test('submit tonight: post draft with blanks + counter, badge snippet, Evidence section with TODOs', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.goto('/a/4d5dbd1bf972')                                       // openai/swarm example
  const post = page.getByTestId('kit-post')
  await expect(post).toHaveValue(/^Team: \[___\]\nName: \[___\]\nProject: swarm[^\n]*\nRepo: https:\/\/github\.com\/openai\/swarm\nDemo: [^\n]+\n#neatHack$/)
  await expect(page.getByTestId('kit-blanks')).toContainText('[___] blank')
  await post.fill('Team: QBITS\nName: Pritam\nProject: ' + 'x'.repeat(300) + '\n#neatHack')
  await expect(page.getByTestId('kit-count')).toContainText('too long')
  await expect(page.getByTestId('kit-badge')).toHaveText(/^\[!\[PreJudge score\]\(.+\/badge\/openai\/swarm\.svg\)\]\(.+\/a\/4d5dbd1bf972\)$/)
  const evidence = page.getByTestId('kit-evidence')
  await expect(evidence).toHaveValue(/^## Evidence/)
  await expect(evidence).toHaveValue(/⚠️ TODO/)
  await page.getByTestId('kit').getByRole('button', { name: 'Copy' }).last().click()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toMatch(/^## Evidence/)
  const badge = await page.request.get('/badge/openai/swarm.svg')
  expect(badge.headers()['content-type']).toContain('image/svg+xml')
  expect(await badge.text()).toMatch(/\d+\/100/)
})

test('judge panel under the score + demo script on request (template in replay mode)', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await watchLayoutShift(page)
  await page.goto('/a/4d5dbd1bf972')
  const judges = page.getByTestId('judge')
  await expect(judges).toHaveCount(3)
  await expect(judges.nth(0)).toContainText('Observability judge')
  await expect(judges.nth(2)).toContainText('Business judge')
  await expect(judges.nth(1)).toContainText('🔧')
  await page.getByRole('button', { name: 'Write my 3-minute demo script' }).click()
  await expect(page.getByTestId('demo-meta')).toContainText('3:00 total · 7 scenes')
  await expect(page.getByTestId('demo-scene')).toHaveCount(7)
  await expect(page.getByTestId('demo-script')).toContainText('TODO: no Entire checkpoint found')   // swarm has none
  await page.getByRole('button', { name: 'Copy script' }).click()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toMatch(/^\[0:00–0:20\]/)
  expect(await layoutShift(page)).toBeLessThan(0.1)
})

test('sponsor depth scorecard on every result page', async ({ page }) => {
  await watchLayoutShift(page)
  await page.goto('/a/4d5dbd1bf972')                                 // openai/swarm: no sponsor tools at all
  const rows = page.getByTestId('sponsor')
  await expect(rows).toHaveCount(3)
  await expect(rows.nth(0)).toContainText('neatlogs')
  await expect(rows.nth(1)).toContainText('Entire')
  await expect(rows.nth(2)).toContainText('cfo.ai')
  await expect(rows.nth(0)).toContainText('Next:')
  await expect(page.getByTestId('sponsors').getByRole('meter').first()).toHaveAttribute('aria-valuenow', /^[0-4]$/)
  await page.waitForTimeout(800)
  expect(await layoutShift(page)).toBeLessThan(0.1)
})

test('glass box: how this verdict was made, collapsed until opened', async ({ page }) => {
  await watchLayoutShift(page)
  await page.goto('/a/4d5dbd1bf972')
  const box = page.getByTestId('glass-box')
  await expect(box).toBeVisible()
  await expect(box).toContainText('Traced with neatlogs')
  await expect(page.getByTestId('glass-totals')).toContainText(/tokens · \$0\.\d{4} · \d+ retr(y|ies) · \d+ fallbacks?/)
  await page.waitForTimeout(500)
  expect(await layoutShift(page)).toBeLessThan(0.1)
  await box.locator('summary').click()
  await expect(box.locator('tbody tr').first()).toBeVisible()
  await expect(box).toContainText('fallback')
  await expect(box).not.toContainText('Error code')
})

test('transparency page: live aggregates, plan vs actual, sponsor links, no repo names', async ({ page }) => {
  await watchLayoutShift(page)
  await page.goto('/')
  await page.getByRole('link', { name: 'Transparency' }).click()
  await expect(page).toHaveURL(/\/transparency$/)
  await expect(page.getByTestId('plan-vs-actual')).toContainText(/plan \$0\.0095|No audits with LLM calls yet/)
  await expect(page.locator('.stat-card')).toHaveCount(8)
  await expect(page.getByRole('link', { name: 'cfo.ai model' })).toHaveAttribute('href', 'https://cfo.ai/s/xBCsLLiMtconXUBf')
  await expect(page.getByRole('link', { name: 'our Entire project page' })).toHaveAttribute('href', /entire\.io\/gh\//)
  await expect(page.getByTestId('transparency')).toContainText('every audit is traced')
  await expect(page.getByTestId('transparency')).not.toContainText('openai/swarm')
  await page.waitForTimeout(800)
  expect(await layoutShift(page)).toBeLessThan(0.1)
})
