import { useState } from 'react'
import { api, ApiError, type Audit, type Stats } from '../api'
import { formatWait } from '../labels'

// "Run deep check": queue the claim verification, then show position and ETA until it's done.
export default function DeepCheck({ audit, stats, onQueued, ready = null, onShow }: {
  audit: Audit
  stats: Stats | null
  onQueued: () => void
  ready?: Audit | null // a finished deep result, waiting for the reader to show it
  onShow?: () => void
}) {
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  // Once this page has shown the deep panel, it stays (with a "done" line) so nothing below it jumps up.
  const [shown, setShown] = useState(false)
  const deep = audit.phases.deep

  if (ready) {
    const claims = ready.result?.agent?.claims?.length ?? 0
    return (
      <section className="panel deep-panel" data-testid="deep-ready">
        <span>
          ✓ Deep check done: {claims} {claims === 1 ? 'claim' : 'claims'} checked against the code, score{' '}
          {ready.result?.score.score ?? '?'}.
        </span>
        <button className="big-button" onClick={onShow}>Show the full result</button>
      </section>
    )
  }
  if (audit.status === 'complete') {
    if (!shown) return null
    const claims = audit.result?.agent?.claims?.length ?? 0
    return (
      <section className="panel deep-panel" data-testid="deep-done">
        <span>✓ Deep check complete: {claims} {claims === 1 ? 'claim' : 'claims'} checked against the code. Each one is listed with its evidence above.</span>
      </section>
    )
  }
  if (deep === 'skipped') return null
  if (!shown) setShown(true)

  if (['queued', 'running', 'waiting_budget'].includes(deep)) {
    const q = audit.queue
    let msg = 'Deep check queued…'
    if (deep === 'running') msg = 'Deep check running: reading the code and judging every claim…'
    else if (deep === 'waiting_budget' || q?.waiting_for_budget)
      msg = "Waiting for the judge models' daily budget. Your spot is saved; this page updates itself."
    else if (q) msg = `Deep check queued: position ${q.position}, ${formatWait(q.estimated_wait_s)}`
    return (
      <section className="panel deep-panel" data-testid="deep-status">
        <span className="spinner" aria-hidden /> <span>{msg}</span>
      </section>
    )
  }

  const run = async () => {
    setSending(true)
    setError(null)
    try {
      await api.requestDeep(audit.id)
      onQueued()
    } catch (e) {
      setError(e instanceof ApiError && e.network ? "Can't reach PreJudge. Try again?" : (e as Error).message)
    } finally {
      setSending(false)
    }
  }

  return (
    <section className="panel deep-panel">
      <div>
        <h2 className="panel-title">Want the full trial?</h2>
        <p className="muted">
          The deep check reads the code, verifies every README claim with file:line evidence and rescores.
          {stats?.budget_state === 'busy' && ` The queue is busy right now (${formatWait(stats.deep_wait_s)}).`}
          {stats?.budget_state === 'cooling' && " The judge models are cooling down; you'll be queued until they're back."}
          {deep === 'failed' && ' The last deep check failed; you can try again.'}
        </p>
      </div>
      <button className="big-button" onClick={run} disabled={sending}>
        {sending ? 'Queuing…' : 'Run deep check'}
      </button>
      {error && <p className="inline-error">{error}</p>}
    </section>
  )
}
