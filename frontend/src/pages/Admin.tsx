import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError, type AdminOverview } from '../api'
import { timeAgo } from '../timeago'

// Admin dashboard. The token is kept in React state only: never in localStorage, a cookie or
// the URL, so closing the tab forgets it.
type Project = AdminOverview['projects'][number]
type SortKey = 'repo_key' | 'last_audit_at' | 'audit_count' | 'deep_count' | 'latest_score' | 'best_score'

const fmt = (n: number | null | undefined) => (n == null ? '–' : n.toLocaleString())

export default function AdminPage() {
  const [token, setToken] = useState('')
  const [draft, setDraft] = useState('')
  const [data, setData] = useState<AdminOverview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: 'last_audit_at', desc: true })

  useEffect(() => {
    const meta = document.createElement('meta')
    meta.name = 'robots'
    meta.content = 'noindex, nofollow'
    document.head.appendChild(meta)
    return () => meta.remove()
  }, [])

  const load = useCallback(async (t: string) => {
    try {
      setData(await api.adminOverview(t))
      setError(null)
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setToken('')
        setError('That token was rejected.')
      } else setError((e as Error).message)
    }
  }, [])

  useEffect(() => {
    if (!token) return
    const first = window.setTimeout(() => load(token), 0)
    const id = window.setInterval(() => load(token), 15000)
    return () => {
      window.clearTimeout(first)
      window.clearInterval(id)
    }
  }, [token, load])

  const projects = useMemo(() => {
    const rows = [...(data?.projects ?? [])]
    rows.sort((a: Project, b: Project) => {
      const x = a[sort.key] ?? -1
      const y = b[sort.key] ?? -1
      return (x < y ? -1 : x > y ? 1 : 0) * (sort.desc ? -1 : 1)
    })
    return rows
  }, [data, sort])

  if (!token)
    return (
      <main className="page narrow" data-testid="admin-login">
        <nav className="topbar"><Link to="/" className="brand">🔥 PreJudge</Link><span className="muted">admin</span></nav>
        <form className="panel" onSubmit={(e) => { e.preventDefault(); setToken(draft.trim()); setDraft('') }}>
          <h1 className="panel-title">Admin token</h1>
          <p className="muted small">Kept in this tab's memory only. Closing the tab forgets it.</p>
          <div className="audit-form">
            <input type="password" autoComplete="off" value={draft}
                   onChange={(e) => setDraft(e.target.value)} aria-label="Admin token" />
            <button className="big-button" type="submit" disabled={!draft.trim()}>Open</button>
          </div>
          {error && <p className="inline-error">{error}</p>}
        </form>
      </main>
    )

  const th = (key: SortKey, label: string) => (
    <th>
      <button className="link-button" onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : true }))}>
        {label}{sort.key === key ? (sort.desc ? ' ▾' : ' ▴') : ''}
      </button>
    </th>
  )

  const b = data?.budget
  const flaggedIps = new Set(data?.limits.by_ip.filter((r) => r.hits >= 3).map((r) => r.key))
  const flaggedRepos = new Set([
    ...(data?.limits.by_repo.filter((r) => r.hits >= 2).map((r) => r.key) ?? []),
    ...(data?.deep.by_repo.filter((r) => r.count >= (data?.deep.per_repo_cap ?? 3)).map((r) => r.repo) ?? []),
  ])

  return (
    <main className="page admin" data-testid="admin">
      <nav className="topbar">
        <Link to="/" className="brand">🔥 PreJudge</Link>
        <span className="muted">admin · {data?.llm_mode ?? '…'}</span>
        <button className="link-button" onClick={() => { setToken(''); setData(null) }}>Forget token</button>
      </nav>
      {error && <p className="notice notice-bad">{error}</p>}
      {!data && <p className="muted">Loading…</p>}
      {data && b && (
        <>
          <section className="admin-tiles">
            <div className="panel tile">
              <span className="tile-label">Public AI budget today</span>
              <span className="tile-num">{fmt(b.public_tokens.used)}</span>
              <span className="muted small">of {fmt(b.public_tokens.cap)} tokens · state: {b.state}</span>
            </div>
            <div className={`panel tile ${data.deep.used_today >= data.deep.daily_cap ? 'tile-hot' : ''}`}>
              <span className="tile-label">Deep checks today</span>
              <span className="tile-num">{data.deep.used_today} / {data.deep.daily_cap}</span>
              <span className="muted small">max {data.deep.per_repo_cap} per repo</span>
            </div>
            <div className="panel tile">
              <span className="tile-label">Queues</span>
              <span className="tile-num">{data.queue.deep} deep</span>
              <span className="muted small">{data.queue.quick} quick · max {data.queue.deep_max}
                {data.queue.waiting_budget ? ' · waiting for budget' : ''}</span>
            </div>
            <div className="panel tile">
              <span className="tile-label">Tokens saved by reuse</span>
              <span className="tile-num">{fmt(data.reuse.tokens_saved_today)}</span>
              <span className="muted small">today ({data.reuse.reused_today} reused) · {fmt(data.reuse.tokens_saved_total)} total</span>
            </div>
          </section>

          <section className="panel">
            <h2 className="panel-title">Budget per model (today)</h2>
            <table className="admin-table">
              <thead><tr><th>Model</th><th>Used</th><th>Public limit</th><th>Daily limit</th><th>Public OK</th></tr></thead>
              <tbody>
                {Object.entries(b.models).map(([m, q]) => (
                  <tr key={m} className={q.ok ? '' : 'row-hot'}>
                    <td><code>{m}</code></td><td>{fmt(q.used)}</td><td>{fmt(q.public_limit)}</td>
                    <td>{fmt(q.limit)}</td><td>{q.ok ? '✓' : '✗'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted small">{b.reserve_pct}% of each model's daily tokens is kept for admin runs.</p>
          </section>

          <section className="panel">
            <h2 className="panel-title">Limits hit</h2>
            {Object.keys(data.limits.today).length === 0 && data.limits.recent.length === 0 && (
              <p className="muted">No limits hit today.</p>
            )}
            {Object.keys(data.limits.today).length > 0 && (
              <p className="small">Today: {Object.entries(data.limits.today).map(([k, v]) =>
                `${k.replace('limit:', '')} ${v}`).join(' · ')}</p>
            )}
            <div className="admin-two">
              <table className="admin-table">
                <thead><tr><th>IP (memory only)</th><th>Hits</th></tr></thead>
                <tbody>{data.limits.by_ip.map((r) => (
                  <tr key={r.key} className={flaggedIps.has(r.key) ? 'row-hot' : ''}><td>{r.key}</td><td>{r.hits}</td></tr>
                ))}</tbody>
              </table>
              <table className="admin-table">
                <thead><tr><th>Repo</th><th>Hits</th></tr></thead>
                <tbody>{data.limits.by_repo.map((r) => (
                  <tr key={r.key} className={flaggedRepos.has(r.key) ? 'row-hot' : ''}><td>{r.key}</td><td>{r.hits}</td></tr>
                ))}</tbody>
              </table>
            </div>
          </section>

          <section className="panel">
            <h2 className="panel-title">Projects ({projects.length})</h2>
            <div className="table-scroll">
              <table className="admin-table">
                <thead><tr>
                  {th('repo_key', 'Repo')}{th('last_audit_at', 'Last audit')}{th('audit_count', 'Audits')}
                  {th('deep_count', 'Deep')}{th('latest_score', 'Latest')}{th('best_score', 'Best')}<th>Hackathon</th>
                </tr></thead>
                <tbody>{projects.map((p) => (
                  <tr key={p.repo_key} className={flaggedRepos.has(p.repo_key) ? 'row-hot' : ''}>
                    <td><a href={p.repo_url} target="_blank" rel="noopener noreferrer">{p.repo_key}</a></td>
                    <td>{p.last_audit_id ? <Link to={`/a/${p.last_audit_id}`}>{p.last_audit_at ? timeAgo(p.last_audit_at) : '–'}</Link> : '–'}</td>
                    <td>{p.audit_count}</td><td>{p.deep_count}</td><td>{fmt(p.latest_score)}</td><td>{fmt(p.best_score)}</td>
                    <td>{p.is_hackathon_repo ? '✓' : ''}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </section>

          <section className="panel">
            <h2 className="panel-title">Recent audits</h2>
            <div className="table-scroll">
              <table className="admin-table">
                <thead><tr><th>Audit</th><th>Repo</th><th>Status</th><th>Deep</th><th>Score</th><th>Tokens</th><th>Kind</th><th>When</th></tr></thead>
                <tbody>{data.recent_audits.map((a) => (
                  <tr key={a.id} className={a.hidden ? 'muted' : ''}>
                    <td><Link to={`/a/${a.id}`}><code>{a.id}</code></Link></td><td>{a.repo_key}</td>
                    <td>{a.status}{a.cached_from ? ' (reused)' : ''}</td><td>{a.phase_deep}</td>
                    <td>{fmt(a.score)}</td><td>{a.cached_from ? '0' : fmt(a.tokens)}</td><td>{a.run_kind}</td>
                    <td>{timeAgo(a.created_at)}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </section>

          <section className="panel">
            <h2 className="panel-title">Feedback ({data.feedback.length})</h2>
            {data.feedback.length === 0 ? <p className="muted">No feedback yet.</p> : (
              <table className="admin-table">
                <thead><tr><th>Audit</th><th>Check</th><th>Note</th><th>When</th></tr></thead>
                <tbody>{data.feedback.map((f) => (
                  <tr key={f.id}><td><Link to={`/a/${f.audit_id}`}><code>{f.audit_id}</code></Link></td>
                    <td>{f.check_id}</td><td>{f.note}</td><td>{timeAgo(f.created_at)}</td></tr>
                ))}</tbody>
              </table>
            )}
          </section>

          <section className="panel">
            <h2 className="panel-title">Per day</h2>
            <p className="muted small" data-testid="admin-unique">
              {fmt(data.metrics.roasts ?? 0)} visible roasts · {fmt(data.metrics.unique_repos ?? 0)} unique repos
              (real runs; examples, tests and removed audits excluded)
            </p>
            <div className="table-scroll">
              <table className="admin-table">
                <thead><tr><th>Day</th><th>Audits</th><th>Reused</th><th>Complete</th><th>Deep</th><th>Tokens saved</th><th>Public tokens</th><th>Cards</th></tr></thead>
                <tbody>{[...data.metrics.days].reverse().map((d) => (
                  <tr key={String(d.day)}>
                    <td>{d.day}</td><td>{fmt(d.audits as number)}</td><td>{fmt((d.reused_audits as number) ?? 0)}</td>
                    <td>{fmt(d.complete as number)}</td><td>{fmt((d.deep_started as number) ?? 0)}</td>
                    <td>{fmt((d.tokens_saved as number) ?? 0)}</td><td>{fmt((d.llm_public_tokens as number) ?? 0)}</td>
                    <td>{fmt(((d.card_png as number) ?? 0) + ((d.card_download as number) ?? 0))}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </main>
  )
}
