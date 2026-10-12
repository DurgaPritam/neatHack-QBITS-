import { useEffect, useState } from 'react'
import { api, type Kit } from '../api'
import { xLength } from '../labels'

function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [done, setDone] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setDone(true)
      window.setTimeout(() => setDone(false), 1500)
    } catch {
      /* clipboard blocked: the text is selectable */
    }
  }
  return (
    <button className="small-button copy-button" onClick={copy} disabled={!text}>
      {done ? 'Copied ✓' : label}
    </button>
  )
}

// Copy-paste helpers for tonight: the submission post, a README badge and an Evidence section.
// Every box has a fixed size before the kit loads, so nothing on the page moves when it arrives.
export default function SubmissionKit({ auditId, status }: { auditId: string; status: string }) {
  const [kit, setKit] = useState<Kit | null>(null)
  const [post, setPost] = useState('')

  useEffect(() => {
    let alive = true
    api
      .kit(auditId)
      .then((k) => {
        if (!alive) return
        setKit(k)
        setPost(k.post.text)
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [auditId, status])

  const n = xLength(post)
  const blanks = (post.match(/\[___\]/g) ?? []).length
  return (
    <section className="panel kit-panel" data-testid="kit">
      <h2 className="panel-title">Submit tonight</h2>

      <div className="kit-block">
        <h3 className="kit-title">Draft my submission post</h3>
        <textarea className="kit-text" rows={7} value={post} onChange={(e) => setPost(e.target.value)}
                  aria-label="Submission post" data-testid="kit-post" spellCheck={false} />
        <div className="kit-row">
          <span className={n > 280 ? 'kit-count over' : 'kit-count'} data-testid="kit-count">
            {n} / 280{n > 280 ? ' · too long for one post: trim the project line' : ''}
          </span>
          {blanks > 0 && <span className="muted small" data-testid="kit-blanks">Fill in the {blanks} [___] blank{blanks > 1 ? 's' : ''}</span>}
          <CopyButton text={post} />
        </div>
      </div>

      <div className="kit-block">
        <h3 className="kit-title">README badge</h3>
        <div className="kit-row">
          <span className="kit-badge">{kit && <img src={kit.badge.url} alt="PreJudge score badge" height={20} />}</span>
          <code className="kit-code" data-testid="kit-badge">{kit?.badge.markdown ?? ' '}</code>
          <CopyButton text={kit?.badge.markdown ?? ''} />
        </div>
      </div>

      <div className="kit-block">
        <h3 className="kit-title">Fix it for me: an Evidence section</h3>
        <p className="muted small kit-note">
          Built from what PreJudge found. Paste it into your README and fill in each ⚠️ TODO before judging.
        </p>
        <textarea className="kit-text" rows={11} readOnly value={kit?.evidence_md ?? ''} aria-label="Evidence section"
                  data-testid="kit-evidence" spellCheck={false} />
        <div className="kit-row">
          <span className="muted small">{kit ? `${(kit.evidence_md.match(/TODO/g) ?? []).length} TODO(s)` : ' '}</span>
          <CopyButton text={kit?.evidence_md ?? ''} />
        </div>
      </div>
    </section>
  )
}
