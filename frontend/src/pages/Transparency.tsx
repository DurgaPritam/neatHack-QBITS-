import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Transparency } from '../api'

const usd = (n: number | null | undefined) => (n == null ? '–' : `$${n.toFixed(4)}`)
const num = (n: number | null | undefined) => (n == null ? '–' : Math.round(n).toLocaleString())
const pct = (n: number | null | undefined) => (n == null ? '–' : `${(n * 100).toFixed(0)}%`)

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="stat-card">
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
      <span className="muted small stat-sub">{sub ?? ' '}</span>
    </div>
  )
}

// Live numbers about PreJudge itself (aggregates only), next to the cfo.ai plan's assumption.
export default function TransparencyPage() {
  const [s, setS] = useState<Transparency | null>(null)
  const [down, setDown] = useState(false)
  useEffect(() => {
    api.transparency().then(setS).catch(() => setDown(true))
  }, [])

  return (
    <main className="page" data-testid="transparency">
      <nav className="topbar"><Link to="/" className="brand">🔥 PreJudge</Link></nav>
      <header>
        <h1 className="headline page-headline">Transparency</h1>
        <p className="lede">
          What PreJudge actually costs and does, live from our database, next to what our business plan assumed.
          Aggregate numbers only: no repo names.
        </p>
      </header>

      <section className="panel plan-panel" data-testid="plan-vs-actual">
        <h2 className="panel-title">Plan vs actual</h2>
        <p className="plan-line">{s ? s.plan_vs_actual : down ? "Can't reach the server right now." : ' '}</p>
        <p className="muted small">
          Plan: $0.005 per quick audit, $0.02 per deep check, 30% deep, so $0.0095 per audit blended, in our{' '}
          <a href="https://cfo.ai/s/xBCsLLiMtconXUBf" target="_blank" rel="noopener noreferrer">cfo.ai model</a>.
          Actual costs are at Groq's list price per token (we run on the free tier, so this is what the same
          tokens would cost).
        </p>
      </section>

      <section className="stat-grid" aria-label="Live numbers">
        <Stat label="audits" value={num(s?.audits)} sub={s ? `${s.reused_results} reused a saved result` : undefined} />
        <Stat label="unique repos" value={num(s?.unique_repos)} />
        <Stat label="actual cost per audit" value={usd(s?.actual.cost_per_audit_usd)} sub={`plan ${usd(s?.plan.cost_per_audit_usd ?? 0.0095)}`} />
        <Stat label="quick audit: avg tokens" value={num(s?.quick.avg_tokens)} sub={s ? `${usd(s.quick.avg_cost_usd)} · ${s.quick.avg_seconds ?? '–'}s avg` : undefined} />
        <Stat label="deep check: avg tokens" value={num(s?.deep.avg_tokens)} sub={s ? `${usd(s.deep.avg_cost_usd)} · ${s.deep.avg_seconds ?? '–'}s avg` : undefined} />
        <Stat label="audits that needed a model fallback" value={pct(s?.fallback_rate)} sub="rate limits handled, not errors" />
        <Stat label="deep check share" value={pct(s?.actual.deep_share)} sub="plan assumes 30%" />
        <Stat label="tokens saved by reuse" value={num(s?.tokens_saved_by_reuse)} sub="unchanged commits get the saved result" />
      </section>

      <section className="panel">
        <h2 className="panel-title">How we know</h2>
        <ul className="plain-list">
          <li>
            <strong>neatlogs:</strong> every audit is traced (session id = audit id): each LLM call, tool call, retry
            and fallback, with tokens and timing. Each result page's "How this verdict was made" panel shows the same
            steps.
          </li>
          <li>
            <strong>cfo.ai:</strong> the <a href={s?.links.cfo_ai ?? 'https://cfo.ai/s/xBCsLLiMtconXUBf'} target="_blank" rel="noopener noreferrer">business model</a>{' '}
            uses these measured costs instead of guesses.
          </li>
          <li>
            <strong>Entire:</strong> how PreJudge was built, checkpoint by checkpoint, on{' '}
            <a href={s?.links.entire ?? 'https://entire.io/gh/DurgaPritam/neatHack-QBITS-'} target="_blank" rel="noopener noreferrer">our Entire project page</a>.
          </li>
        </ul>
        <p className="muted small">{s ? `Updated ${s.generated_at.replace('T', ' ').replace('Z', ' UTC')} · refreshed every 5 minutes` : ' '}</p>
      </section>
    </main>
  )
}
