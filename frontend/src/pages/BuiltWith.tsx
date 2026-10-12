import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

interface CommitRef { sha: string; url: string; subject: string; checkpoint: string | null; checkpoint_url: string | null }
interface Story {
  generated_at: string
  repo: string
  entire_project: string
  commits: number
  commits_in_window: number
  first_commit: string | null
  last_commit: string | null
  checkpoint_commits: number
  checkpoint_ids: number
  checkpoint_refs: number
  checkpoints: { sha: string; date: string; subject: string; checkpoint: string; url: string; commit_url: string }[]
  improvements: { improvement: string; before: string; after: string; commits: CommitRef[] }[]
}

const day = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata' }) + ' IST' : '–'

// Our own build story: from git (pushed commits only), Entire checkpoints and EVIDENCE.md.
// Generated at deploy time by scripts/built_with.py into /built-with.json.
export default function BuiltWithPage() {
  const [s, setS] = useState<Story | null>(null)
  const [down, setDown] = useState(false)
  useEffect(() => {
    fetch('/built-with.json').then((r) => (r.ok ? r.json() : Promise.reject())).then(setS).catch(() => setDown(true))
  }, [])

  return (
    <main className="page" data-testid="built-with">
      <nav className="topbar"><Link to="/" className="brand">🔥 PreJudge</Link></nav>
      <header>
        <h1 className="headline page-headline">Built with</h1>
        <p className="lede">
          How PreJudge was built during neatHack: every commit is on GitHub, and each Entire checkpoint links the
          AI session that produced it. The improvements below are measured before and after.
        </p>
      </header>

      <section className="stat-grid" aria-label="Build numbers">
        <div className="stat-card"><span className="stat-value">{s?.commits ?? '–'}</span><span className="stat-label">commits</span>
          <span className="muted small stat-sub">{s ? `${s.commits_in_window} inside the hackathon window` : ' '}</span></div>
        <div className="stat-card"><span className="stat-value">{s?.checkpoint_commits ?? '–'}</span><span className="stat-label">commits with an Entire checkpoint</span>
          <span className="muted small stat-sub">{s ? `${s.checkpoint_refs} checkpoint refs pushed` : ' '}</span></div>
        <div className="stat-card"><span className="stat-value">{s?.improvements.length ?? '–'}</span><span className="stat-label">measured improvements</span>
          <span className="muted small stat-sub">before → after, from EVIDENCE.md</span></div>
        <div className="stat-card"><span className="stat-value stat-value-small">{s ? day(s.first_commit) : '–'}</span><span className="stat-label">first commit</span>
          <span className="muted small stat-sub">{s ? `last: ${day(s.last_commit)}` : ' '}</span></div>
      </section>
      {down && <p className="inline-error">Couldn't load the build story.</p>}

      <section className="panel">
        <h2 className="panel-title">Before → after</h2>
        <div className="table-scroll">
          <table className="glass-table" data-testid="improvements">
            <thead><tr><th>Improvement</th><th>Before</th><th>After</th><th>Commit · checkpoint</th></tr></thead>
            <tbody>
              {(s?.improvements ?? []).map((r, i) => (
                <tr key={i}>
                  <td>{r.improvement}</td><td>{r.before}</td><td>{r.after}</td>
                  <td className="small">
                    {r.commits.map((c) => (
                      <span key={c.sha} className="commit-ref">
                        <a href={c.url} target="_blank" rel="noopener noreferrer"><code>{c.sha}</code></a>
                        {c.checkpoint_url && (
                          <> · <a href={c.checkpoint_url} target="_blank" rel="noopener noreferrer">Entire checkpoint</a></>
                        )}
                      </span>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <h2 className="panel-title">Entire checkpoints ({s?.checkpoint_commits ?? 0})</h2>
        <p className="muted small">
          Each links to the checkpoint on entire.io: the session transcript, prompts and files behind that commit.{' '}
          {s && <a href={s.entire_project} target="_blank" rel="noopener noreferrer">All checkpoints on Entire</a>}
        </p>
        <ol className="checkpoint-list" data-testid="checkpoints">
          {(s?.checkpoints ?? []).map((c) => (
            <li key={c.sha}>
              <a href={c.url} target="_blank" rel="noopener noreferrer"><code>{c.checkpoint}</code></a>{' '}
              <span className="muted small">{day(c.date)} ·</span>{' '}
              <a href={c.commit_url} target="_blank" rel="noopener noreferrer" className="muted small"><code>{c.sha}</code></a>{' '}
              {c.subject}
            </li>
          ))}
        </ol>
        <p className="muted small">{s ? `Generated from pushed commits at ${s.generated_at.replace('T', ' ').replace('Z', ' UTC')}.` : ' '}</p>
      </section>
    </main>
  )
}
