import { useState } from 'react'
import { api } from '../api'

// "This verdict is wrong": a small inline form, one per check or claim.
export default function FeedbackButton({ auditId, checkId }: { auditId: string; checkId: string }) {
  const [state, setState] = useState<'idle' | 'open' | 'sending' | 'sent' | 'error'>('idle')
  const [note, setNote] = useState('')

  if (state === 'sent') return <span className="feedback-sent">Thanks, noted.</span>
  if (state === 'idle')
    return (
      <button className="link-button" onClick={() => setState('open')}>
        This verdict is wrong
      </button>
    )

  const send = async () => {
    setState('sending')
    try {
      await api.feedback(auditId, checkId, note)
      setState('sent')
    } catch {
      setState('error')
    }
  }
  return (
    <div className="feedback-form">
      <label className="sr-only" htmlFor={`fb-${checkId}`}>What's wrong?</label>
      <input
        id={`fb-${checkId}`}
        value={note}
        maxLength={500}
        placeholder="What's wrong? (optional)"
        onChange={(e) => setNote(e.target.value)}
      />
      <button className="small-button" onClick={send} disabled={state === 'sending'}>
        {state === 'sending' ? 'Sending…' : 'Send'}
      </button>
      {state === 'error' && <span className="feedback-error">Couldn't send. Try again?</span>}
    </div>
  )
}
