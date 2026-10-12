// Measures cumulative layout shift (CLS) on the home page and an audit page, desktop + mobile.
//   node e2e/cls.mjs <base-url> [audit-id]      e.g. node e2e/cls.mjs http://localhost:5173 abc123
// CLS_LIVE=<repo url> also measures a live audit: submit from the home page, watch the quick result
// arrive, then run the deep check and watch it finish (local replay stack only: it spends LLM budget live).
import { chromium } from 'playwright'

const base = process.argv[2] ?? 'http://localhost:5173'
let auditId = process.argv[3]
const WATCH_MS = Number(process.env.CLS_WATCH_MS ?? 12000)
const sizes = { desktop: { width: 1280, height: 800 }, mobile: { width: 390, height: 844 } }

const observe = () => {
  window.__cls = { value: 0, sources: [] }
  new PerformanceObserver((list) => {
    for (const e of list.getEntries()) {
      if (e.hadRecentInput) continue
      window.__cls.value += e.value
      for (const s of e.sources ?? []) {
        const n = s.node
        const name = n && n.nodeType === 1 ? `${n.tagName.toLowerCase()}${n.className ? '.' + String(n.className).split(' ').join('.') : ''}` : n ? '#text:' + (n.parentElement?.className ?? '') : '?'
        window.__cls.sources.push({ value: +e.value.toFixed(4), node: name, at: Math.round(e.startTime), dy: Math.round(s.currentRect.y - s.previousRect.y), y: Math.round(s.previousRect.y) })
      }
    }
  }).observe({ type: 'layout-shift', buffered: true })
}

const browser = await chromium.launch({ channel: process.env.E2E_CHANNEL ?? 'chrome' })
if (!auditId) {
  const r = await fetch(`${base.replace(/\/$/, '')}/api/examples`).then((r) => r.json()).catch(() => [])
  auditId = r[0]?.id
}
const out = {}
for (const [label, viewport] of Object.entries(sizes)) {
  for (const [page, path] of [['home', '/'], ['audit', `/a/${auditId}`]]) {
    const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1 })
    const p = await ctx.newPage()
    await p.addInitScript(observe)
    await p.goto(base + path, { waitUntil: 'load' })
    await p.waitForTimeout(WATCH_MS)
    const r = await p.evaluate(() => window.__cls)
    const overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    out[`${page} ${label}`] = { cls: +r.value.toFixed(4), overflow_px: overflow, top: r.sources.sort((a, b) => b.value - a.value).slice(0, 6) }
    await ctx.close()
  }
}
const live = process.env.CLS_LIVE
const liveRepos = (live ?? '').split(',')
if (live) {
  for (const [label, viewport] of Object.entries(sizes)) {
    const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1 })
    const p = await ctx.newPage()
    await p.addInitScript(observe)
    await p.goto(base + '/', { waitUntil: 'load' })
    await p.getByLabel('GitHub repo URL').fill(liveRepos[label === 'desktop' ? 0 : liveRepos.length - 1])
    await p.getByRole('button', { name: 'Roast my repo' }).click()
    await p.waitForURL(/\/a\//)
    await p.evaluate(() => { window.__cls.value = 0; window.__cls.sources = [] })  // the audit page alone
    await p.waitForTimeout(1500)
    const deep = p.getByRole('button', { name: 'Run deep check' })
    await deep.waitFor({ timeout: 60000 }).catch(() => {})
    const quick = await p.evaluate(() => structuredClone(window.__cls))
    if (await deep.isVisible().catch(() => false)) {
      // a click is "recent input": shifts in the next 500 ms don't count, the deep result later does
      await deep.click()
      const ready = p.getByRole('button', { name: 'Show the full result' })
      await Promise.race([ready.waitFor({ timeout: 120000 }), p.getByText('What the judge did').waitFor({ timeout: 120000 })])
        .catch(() => {})
      await p.waitForTimeout(2500)
      if (await ready.isVisible().catch(() => false)) {
        await ready.click()
        await p.waitForTimeout(2500)
      }
    }
    const r = await p.evaluate(() => window.__cls)
    const overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    out[`live audit ${label}`] = { cls_until_quick: +quick.value.toFixed(4), cls: +r.value.toFixed(4), overflow_px: overflow,
      top: r.sources.sort((a, b) => b.value - a.value).slice(0, Number(process.env.CLS_TOP ?? 6)) }
    await ctx.close()
  }
}
await browser.close()
console.log(JSON.stringify(out, null, 1))
