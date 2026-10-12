import { useState } from 'react'
import { api, ApiError, type Audit } from '../api'

// Opt in to the homepage's "Fresh off the grill" feed. Off by default; the team can switch it back off.
export default function ShowcaseToggle({ audit }: { audit: Audit }) {
  const [on, setOn] = useState(Boolean(audit.showcase))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const change = async (next: boolean) => {
    setBusy(true)
    setError(null)
    setOn(next) // flip now, undo if the server says no
    try {
      const r = await api.setShowcase(audit.id, next)
      setOn(r.showcase)
    } catch (e) {
      setOn(!next)
      setError(e instanceof ApiError && e.network ? "Can't reach PreJudge. Try again?" : (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <label className="showcase-toggle" data-testid="showcase-toggle">
      <input type="checkbox" checked={on} disabled={busy} onChange={(e) => change(e.target.checked)} />
      <span>
        Show my roast on the homepage
        <span className="muted small"> · repo name, score and roast, in the "Fresh off the grill" feed</span>
      </span>
      {error && <span className="inline-error small">{error}</span>}
    </label>
  )
}
