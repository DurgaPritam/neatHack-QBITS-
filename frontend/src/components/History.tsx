import type { Audit } from '../api'
import { timeAgo } from '../timeago'

// Reuse notice, progress since the last check, and anonymous percentiles.
export default function History({ audit }: { audit: Audit }) {
  const r = audit.result
  if (!r) return null
  const reuse = r.reuse
  const progress = r.progress
  const pct = audit.percentiles
  if (!reuse && !progress && !pct) return null
  return (
    <section className="panel history-panel" data-testid="history">
      {reuse && (
        <p className="notice notice-cool" data-testid="reuse-notice">
          {reuse.deep ? 'No new commits since the last deep check' : 'No new commits since your last check'}{' '}
          {timeAgo(reuse.checked_at)}, so here's that result. Push your fixes and check again.
        </p>
      )}
      {progress && (
        <div className={`progress progress-${progress.delta > 0 ? 'up' : progress.delta < 0 ? 'down' : 'same'}`}
             data-testid="progress">
          <strong>{progress.text}</strong>
          {progress.fixed.length > 0 && (
            <span className="muted small"> · Fixed: {progress.fixed.join(', ')}</span>
          )}
          {progress.regressed.length > 0 && (
            <span className="muted small"> · Slipped: {progress.regressed.join(', ')}</span>
          )}
        </div>
      )}
      {pct && (
        <div className="percentiles" data-testid="percentiles">
          <p className="pct-headline">{pct.text}.</p>
          <ul className="pct-list">
            {pct.checks.map((c) => (
              <li key={c.check_id} className={c.passed ? 'pct-pass' : 'muted'}>{c.text}</li>
            ))}
          </ul>
          <p className="muted small">
            Compared anonymously with {pct.cohort_size} repos that have commits in the neatHack window. No names,
            no leaderboard.
          </p>
        </div>
      )}
    </section>
  )
}
