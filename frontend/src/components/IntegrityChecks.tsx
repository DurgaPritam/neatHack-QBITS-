import type { Integrity } from '../api'

const LABEL = { ok: 'ok', look: 'needs a human look', unknown: "couldn't check" } as const
const ICON = { ok: '✓', look: '👀', unknown: '?' } as const

// Integrity checks: does the evidence line up with what we can observe? Never part of the score;
// neutral wording, the exact reason, and how to fix it if it's innocent.
export default function IntegrityChecks({ data }: { data: Integrity }) {
  const order = { look: 0, unknown: 1, ok: 2 }
  const signals = [...data.signals].sort((a, b) => order[a.status] - order[b.status])
  return (
    <section className="panel integrity-panel" data-testid="integrity">
      <h2 className="panel-title">Integrity checks</h2>
      <p className="muted small integrity-sub" data-testid="integrity-counts">
        Not part of the score. {data.counts.ok} ok · {data.counts.look} need{data.counts.look === 1 ? 's' : ''} a human
        look · {data.counts.unknown} couldn't check. A mismatch often has an innocent reason (a rebase, a template, a typo):
        each one says how to clear it.
      </p>
      <ul className="integrity-list">
        {signals.map((s) => (
          <li key={s.id} className={`integrity-item integrity-${s.status}`} data-testid="integrity-signal" data-status={s.status}>
            <div className="integrity-head">
              <span className="integrity-icon" aria-hidden>{ICON[s.status]}</span>
              <strong>{s.title}</strong>
              <span className={`badge integrity-badge-${s.status}`}>{LABEL[s.status]}</span>
            </div>
            <p className="small integrity-reason">{s.reason}</p>
            <p className="muted small integrity-checked">Checked: {s.checked}</p>
            {s.evidence.length > 0 && (
              <ul className="evidence">
                {s.evidence.map((e) => (
                  <li key={e}>{e.startsWith('http') ? <a href={e} target="_blank" rel="noopener noreferrer">{e}</a> : <code>{e}</code>}</li>
                ))}
              </ul>
            )}
            {s.fix && <p className="small integrity-fix">If this is innocent: {s.fix}</p>}
          </li>
        ))}
      </ul>
    </section>
  )
}
