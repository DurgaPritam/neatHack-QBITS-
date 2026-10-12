import type { GlassBox as Box } from '../api'
import { numberedLabels } from '../labels'

const usd = (n: number) => (n === 0 ? '–' : n < 0.0001 ? '<$0.0001' : `$${n.toFixed(4)}`)
const secs = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`)
const BADGE: Record<string, string> = { retry: 'retry', fallback: 'fallback', wait: 'quota wait', failed: 'failed' }

// "How this verdict was made": every step with its time, tokens and list-price cost, plus retries and
// fallbacks, from the audit's stored step log. Collapsed by default (opening it is the only movement).
export default function GlassBox({ box, auditId }: { box: Box; auditId: string }) {
  const t = box.totals
  const labels = numberedLabels(box.steps.map((s) => s.name))
  return (
    <details className="panel glass-panel" data-testid="glass-box">
      <summary className="glass-summary">
        <span className="panel-title glass-title">How this verdict was made</span>
        <span className="muted small glass-totals" data-testid="glass-totals">
          {secs(t.ms)} · {t.tokens.toLocaleString()} tokens · {usd(t.cost_usd)} · {t.retries} retr{t.retries === 1 ? 'y' : 'ies'} ·{' '}
          {t.fallbacks} fallback{t.fallbacks === 1 ? '' : 's'}
        </span>
        <span className="glass-badge">Traced with neatlogs</span>
      </summary>
      <p className="muted small">
        Every step of this audit, from our own step log. The full trace lives in neatlogs (session = audit{' '}
        <code>{auditId}</code>). Costs are at {box.pricing.charAt(0).toLowerCase() + box.pricing.slice(1)}.
        {Object.entries(box.phases).map(([ph, p]) => (
          <span key={ph}> {ph === 'quick' ? 'Quick' : 'Deep'} phase: {p.tokens.toLocaleString()} tokens, {p.calls} LLM calls, {usd(p.cost_usd)}{p.ms ? `, ${secs(p.ms)}` : ''}.</span>
        ))}
      </p>
      <div className="table-scroll">
        <table className="glass-table">
          <thead>
            <tr><th>Step</th><th>Model</th><th>Time</th><th>Tokens</th><th>Cost</th></tr>
          </thead>
          <tbody>
            {box.steps.map((s, i) => (
              <tr key={i} className={s.kind ? `glass-${s.kind}` : undefined}>
                <td>
                  {labels[i]}
                  {s.kind && <span className={`glass-kind glass-kind-${s.kind}`}>{BADGE[s.kind]}</span>}
                  {s.kind === 'wait' && s.wait_s ? <span className="muted small"> {s.wait_s}s</span> : null}
                  {s.note && <div className="muted small glass-note">{s.note}</div>}
                </td>
                <td className="muted small">{s.model ?? ''}</td>
                <td className="num">{s.ms ? secs(s.ms) : ''}</td>
                <td className="num">{s.tokens ? s.tokens.toLocaleString() : ''}</td>
                <td className="num">{s.tokens ? usd(s.cost_usd) : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  )
}
