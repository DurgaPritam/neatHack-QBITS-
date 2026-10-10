import type { Step } from '../api'
import { stepLabel } from '../labels'

const ICON: Record<Step['status'], string> = { ok: '✓', failed: '✗', skipped: '–' }

export default function StepLog({ steps, live }: { steps: Step[]; live: boolean }) {
  return (
    <section className="panel steplog" aria-live="polite">
      <h2 className="panel-title">{live ? 'Judging in progress' : 'What the judge did'}</h2>
      <ol>
        {steps.map((s, i) => (
          <li key={i} className={`step step-${s.status}`}>
            <span className="step-icon" aria-hidden>{ICON[s.status]}</span>
            <span className="step-label">{stepLabel(s.name)}</span>
            {s.status !== 'ok' && s.detail && <span className="step-detail">{s.detail.slice(0, 140)}</span>}
            {s.duration_ms > 400 && <span className="step-time">{(s.duration_ms / 1000).toFixed(1)}s</span>}
          </li>
        ))}
        {live && (
          <li className="step step-running">
            <span className="spinner" aria-hidden />
            <span className="step-label">Working…</span>
          </li>
        )}
      </ol>
    </section>
  )
}
