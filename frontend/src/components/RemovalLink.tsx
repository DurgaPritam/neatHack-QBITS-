import { useState } from 'react'
import { api, ApiError } from '../api'

// "Request removal": hides this audit from public view right away. An admin can restore it.
export default function RemovalLink({ auditId, onRemoved }: { auditId: string; onRemoved: () => void }) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    setSending(true)
    setError(null)
    try {
      await api.requestRemoval(auditId, reason.trim())
      onRemoved()
    } catch (e) {
      setError(e instanceof ApiError && e.network ? "Can't reach PreJudge. Try again?" : (e as Error).message)
    } finally {
      setSending(false)
    }
  }

  if (!open)
    return (
      <p className="removal muted small">
        Is this your repo and you'd rather it wasn't here?{' '}
        <button className="link-button" onClick={() => setOpen(true)} data-testid="request-removal">
          Request removal
        </button>
      </p>
    )
  return (
    <section className="panel removal-panel" data-testid="removal-form">
      <h2 className="panel-title">Remove this audit from public view?</h2>
      <p className="muted small">The page, its roast card and share link stop working right away.</p>
      <input
        className="text-input"
        value={reason}
        maxLength={300}
        onChange={(e) => setReason(e.target.value)}
        placeholder="Reason (optional)"
        aria-label="Reason for removal (optional)"
      />
      <div className="button-row">
        <button className="big-button" onClick={submit} disabled={sending}>
          {sending ? 'Removing…' : 'Remove it'}
        </button>
        <button className="link-button" onClick={() => setOpen(false)}>Cancel</button>
      </div>
      {error && <p className="inline-error">{error}</p>}
    </section>
  )
}
