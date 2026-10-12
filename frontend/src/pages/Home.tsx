import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError, looksLikeRepo, type Example, type Stats } from '../api'
import { BUILT_WITH, scoreTone } from '../labels'
import BudgetBanner from '../components/BudgetBanner'

export default function Home() {
  const navigate = useNavigate()
  const [url, setUrl] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [stats, setStats] = useState<Stats | null>(null)
  const [statsDown, setStatsDown] = useState(false)
  const [examples, setExamples] = useState<Example[]>([])

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const s = await api.stats()
        if (alive) {
          setStats(s)
          setStatsDown(false)
        }
      } catch {
        if (alive) setStatsDown(true)
      }
    }
    // "Fresh off the grill": opted-in roasts (topped up with examples), refreshed every 30s. Cards have a
    // fixed height, so a refresh swaps text in place instead of moving the page.
    const feed = () => api.showcase().then((e) => alive && setExamples(e)).catch(() => {})
    load()
    feed()
    const t = setInterval(load, 10_000)
    const f = setInterval(feed, 30_000)
    return () => {
      alive = false
      clearInterval(t)
      clearInterval(f)
    }
  }, [])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if (!looksLikeRepo(url)) {
      setError('Paste a public GitHub repo, like https://github.com/owner/repo')
      return
    }
    setSending(true)
    try {
      const r = await api.createAudit(url.trim())
      navigate(`/a/${r.id}`)
    } catch (err) {
      setError(err instanceof ApiError && err.network ? "Can't reach PreJudge right now. Try again in a moment." : (err as Error).message)
      setSending(false)
    }
  }

  return (
    <main className="page">
      <header className="hero">
        <p className="kicker">🔥 PreJudge · #neatHack</p>
        <h1 className="headline">Get roasted before the judges do</h1>
        <p className="lede">
          Paste your hackathon repo. An AI judge checks it against the neatHack rubric, verifies your README
          claims in the code, and tells you exactly what to fix. With jokes.
        </p>
        <form className="audit-form" onSubmit={submit} noValidate>
          <label className="sr-only" htmlFor="repo-url">GitHub repo URL</label>
          <input
            id="repo-url"
            type="url"
            inputMode="url"
            autoComplete="off"
            placeholder="https://github.com/you/your-hackathon-repo"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          <button className="big-button" type="submit" disabled={sending}>
            {sending ? 'Lighting the oven…' : 'Roast my repo'}
          </button>
        </form>
        {error && <p className="inline-error" role="alert">{error}</p>}
        <p className="counter" data-testid="counter">
          {statsDown ? (
            <span className="muted">Can't reach the server right now.</span>
          ) : stats ? (
            <>
              <strong>{stats.total_audits.toLocaleString()}</strong> {stats.total_audits === 1 ? 'roast' : 'roasts'}
            </>
          ) : (
            <span className="muted">&nbsp;</span>
          )}
        </p>
        {stats && <BudgetBanner state={stats.budget_state} waitS={stats.deep_wait_s} />}
      </header>

      <section className="examples">
        <h2 className="section-title">Fresh off the grill</h2>
        <p className="muted small section-sub">Roasts from teams who chose to show theirs, plus a few classics.</p>
        <div className="example-grid">
          {/* placeholders hold the grid's height until the roasts load: the footer never jumps */}
          {examples.length === 0 &&
            [0, 1, 2].map((i) => <div key={i} className="example-card example-skeleton" aria-hidden />)}
          {examples.map((e) => (
            <Link key={e.id} to={`/a/${e.id}`} className="example-card" data-testid="example"
                  data-example={e.example ? 'builtin' : 'opted-in'}>
              <span className={`example-score tone-${scoreTone(e.score)}`}>{e.score ?? '?'}</span>
              <span className="example-repo">{e.repo}</span>
              {e.roast && <span className="example-roast">“{e.roast.length > 160 ? e.roast.slice(0, 157) + '…' : e.roast}”</span>}
            </Link>
          ))}
        </div>
      </section>

      <footer className="footer">
        Reads your repo through the GitHub API only. Never runs your code. No accounts.
        <span className="footer-links">
          <Link to="/transparency">Transparency</Link>
          {BUILT_WITH && <> · <Link to="/built-with">Built with</Link></>}
        </span>
      </footer>
    </main>
  )
}
