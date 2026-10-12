import { useEffect, useState } from 'react'
import { api, type JudgePanel as Panel } from '../api'

const TITLES = ['Observability judge', 'Dev-workflow judge', 'Business judge']

// Three generic judge personas (never real people), one praise + one fix each, from this audit's facts.
// The three cards keep their size while loading, so nothing below them moves.
export default function JudgePanel({ auditId, status }: { auditId: string; status: string }) {
  const [panel, setPanel] = useState<Panel | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let alive = true
    api
      .judgePanel(auditId)
      .then((p) => alive && setPanel(p))
      .catch(() => alive && setFailed(true))
    return () => {
      alive = false
    }
  }, [auditId, status])

  return (
    <section className="judge-panel" data-testid="judge-panel" aria-label="Judge panel">
      {(panel?.judges ?? TITLES.map((title) => ({ id: title, title, praise: '', fix: '' }))).map((j) => (
        <article key={j.id} className="judge-card" data-testid="judge">
          <h3 className="judge-title">{j.title}</h3>
          {panel ? (
            <>
              <p className="judge-praise">👍 {j.praise}</p>
              <p className="judge-fix">🔧 {j.fix}</p>
            </>
          ) : (
            <p className="muted small">{failed ? "Couldn't reach the panel." : 'Deliberating…'}</p>
          )}
        </article>
      ))}
    </section>
  )
}
