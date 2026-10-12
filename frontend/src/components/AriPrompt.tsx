import { useState } from 'react'
import { api, ApiError, type AriPrompt as Prompt } from '../api'

// "Write my cfo.ai prompt": a ready-to-paste prompt for Ari from the numbers in the README, [___] for
// the rest. Fixed-height box: writing it never moves the page.
export default function AriPrompt({ auditId }: { auditId: string }) {
  const [p, setP] = useState<Prompt | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const write = async () => {
    setBusy(true)
    setError(null)
    try {
      setP(await api.ariPrompt(auditId))
    } catch (e) {
      setError(e instanceof ApiError && e.network ? "Can't reach PreJudge. Try again?" : (e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const copy = async () => {
    if (!p) return
    try {
      await navigator.clipboard.writeText(p.prompt)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard blocked: the text is selectable */
    }
  }

  return (
    <section className="panel ari-panel" data-testid="ari-prompt">
      <div className="kit-row">
        <h2 className="panel-title demo-title">Your cfo.ai prompt for Ari</h2>
        {p ? (
          <button className="small-button copy-button" onClick={copy}>{copied ? 'Copied ✓' : 'Copy prompt'}</button>
        ) : (
          <button className="small-button copy-button" onClick={write} disabled={busy}>
            {busy ? 'Writing…' : 'Write my cfo.ai prompt'}
          </button>
        )}
      </div>
      <div className="ari-box">
        {!p && !busy && !error && (
          <p className="muted">
            A prompt to paste into Ari on cfo.ai, using the pricing, cost and usage numbers in your README, with
            [___] blanks for the ones you still need. It ends with a reminder to export and link the plan.
          </p>
        )}
        {busy && <p className="muted"><span className="spinner" aria-hidden /> Reading your README's numbers…</p>}
        {error && <p className="inline-error">{error}</p>}
        {p && (
          <>
            <p className="muted small" data-testid="ari-meta">
              {p.numbers_found.length} number line{p.numbers_found.length === 1 ? '' : 's'} found in your README ·{' '}
              {p.blanks} [___] blank{p.blanks === 1 ? '' : 's'} to fill
              {p.source === 'template' ? ' · template (the AI budget is busy)' : ''}
            </p>
            <textarea className="kit-text ari-text" readOnly value={p.prompt} aria-label="cfo.ai prompt"
                      data-testid="ari-text" spellCheck={false} />
          </>
        )}
      </div>
    </section>
  )
}
