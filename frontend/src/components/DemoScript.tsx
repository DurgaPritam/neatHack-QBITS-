import { useState } from 'react'
import { api, ApiError, type DemoScript as Script } from '../api'

// "Write my 3-minute demo script": one LLM call grounded in this audit (a template if the budget is out).
// The script lives in a fixed-height box, so writing it never moves the page.
export default function DemoScript({ auditId }: { auditId: string }) {
  const [script, setScript] = useState<Script | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const write = async () => {
    setBusy(true)
    setError(null)
    try {
      setScript(await api.demoScript(auditId))
    } catch (e) {
      setError(e instanceof ApiError && e.network ? "Can't reach PreJudge. Try again?" : (e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const copy = async () => {
    if (!script) return
    try {
      await navigator.clipboard.writeText(script.text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard blocked: the text is selectable */
    }
  }

  return (
    <section className="panel demo-panel" data-testid="demo-script">
      <div className="kit-row">
        <h2 className="panel-title demo-title">Your 3-minute demo script</h2>
        {script ? (
          <button className="small-button copy-button" onClick={copy}>{copied ? 'Copied ✓' : 'Copy script'}</button>
        ) : (
          <button className="small-button copy-button" onClick={write} disabled={busy}>
            {busy ? 'Writing…' : 'Write my 3-minute demo script'}
          </button>
        )}
      </div>
      <div className="demo-box" aria-live="polite">
        {!script && !busy && !error && (
          <p className="muted">
            Scenes with times (3:00 in total), what to show and what to say. It covers neatlogs, Entire and cfo.ai,
            uses only what this audit found, and marks anything missing as TODO.
          </p>
        )}
        {busy && <p className="muted"><span className="spinner" aria-hidden /> Writing from this audit's facts…</p>}
        {error && <p className="inline-error">{error}</p>}
        {script && (
          <>
            <p className="muted small" data-testid="demo-meta">
              {script.total} total · {script.scenes.length} scenes
              {script.todos > 0 ? ` · ${script.todos} TODO${script.todos > 1 ? 's' : ''} to fill before you record` : ''}
              {script.source === 'template' ? ' · template (the AI budget is busy)' : ''}
            </p>
            <ol className="demo-scenes">
              {script.scenes.map((s) => (
                <li key={s.id} className={s.todo ? 'demo-scene demo-todo' : 'demo-scene'} data-testid="demo-scene">
                  <span className="demo-time">{s.start}–{s.end}</span>
                  <strong>{s.topic}</strong>
                  <span><b>Show:</b> {s.show}</span>
                  <span><b>Say:</b> {s.say}</span>
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
    </section>
  )
}
