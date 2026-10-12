import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError, type Audit, type Stats } from '../api'
import DeepCheck from '../components/DeepCheck'
import History from '../components/History'
import RemovalLink from '../components/RemovalLink'
import ShowcaseToggle from '../components/ShowcaseToggle'
import Result from '../components/Result'
import RoastCard from '../components/RoastCard'
import StepLog from '../components/StepLog'
import SubmissionKit from '../components/SubmissionKit'

const POLL_MS = 1500
const ACTIVE_DEEP = ['queued', 'running', 'waiting_budget']

function isActive(a: Audit | null): boolean {
  if (!a) return true
  return a.status === 'queued' || ACTIVE_DEEP.includes(a.phases.deep)
}

export default function AuditPage() {
  const { id = '' } = useParams()
  const [audit, setAudit] = useState<Audit | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [removed, setRemoved] = useState(false)
  const [offline, setOffline] = useState(false)
  const [tick, setTick] = useState(0)
  // A finished deep check rewrites the result above where the reader is looking; hold it until they ask.
  const [pending, setPending] = useState<Audit | null>(null)
  const shown = useRef<Audit | null>(null)
  const timer = useRef<number | undefined>(undefined)

  const show = (a: Audit) => {
    shown.current = a
    setAudit(a)
  }

  const poll = useCallback(async () => {
    try {
      const a = await api.getAudit(id)
      const prev = shown.current
      if (prev?.result && prev.status !== 'complete' && a.status === 'complete') {
        setPending(a)
        show({ ...prev, steps: a.steps, phases: a.phases })
      } else show(a)
      setOffline(false)
      return a
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setNotFound(true)
      else if (e instanceof ApiError && e.status === 410) setRemoved(true)
      else setOffline(true)
      return null
    }
  }, [id])

  // Poll every 1.5s while anything is still running (quick phase or a requested deep check).
  useEffect(() => {
    let alive = true
    const loop = async () => {
      const a = await poll()
      if (!alive) return
      if (isActive(a) && !notFound && !removed) timer.current = window.setTimeout(loop, POLL_MS)
    }
    loop()
    return () => {
      alive = false
      window.clearTimeout(timer.current)
    }
  }, [poll, tick, notFound, removed])

  // Results pages stay out of search engines (Caddy also sends X-Robots-Tag for /a/*).
  useEffect(() => {
    const meta = document.createElement('meta')
    meta.name = 'robots'
    meta.content = 'noindex, nofollow'
    document.head.appendChild(meta)
    return () => meta.remove()
  }, [])

  useEffect(() => {
    api.stats().then(setStats).catch(() => {})
  }, [tick])

  if (removed)
    return (
      <main className="page narrow" data-testid="audit-removed">
        <h1 className="headline">This audit was removed.</h1>
        <p className="lede">
          It's hidden from public view at the owner's request. <Link to="/">Audit a repo</Link>.
        </p>
      </main>
    )

  if (notFound)
    return (
      <main className="page narrow">
        <h1 className="headline">No such audit.</h1>
        <p className="lede">
          That link doesn't match any roast. <Link to="/">Audit a repo</Link>.
        </p>
      </main>
    )

  const report = audit?.result
  const live = !audit || audit.status === 'queued'
  return (
    <main className="page">
      <nav className="topbar">
        <Link to="/" className="brand">🔥 PreJudge</Link>
        {audit && <span className="muted small topbar-repo">{audit.repo_url.replace(/^https?:\/\/(www\.)?github\.com\//, '')}</span>}
      </nav>

      {offline && (
        <p className="notice notice-bad" role="alert" data-testid="offline">
          Lost connection to PreJudge. Retrying…{' '}
          <button className="link-button" onClick={() => setTick((t) => t + 1)}>Retry now</button>
        </p>
      )}

      {audit?.status === 'failed' && (
        <section className="panel error-panel" data-testid="audit-failed">
          <h1 className="headline">The judge tripped.</h1>
          <p className="lede">Something went wrong on our side ({audit.error ?? 'unknown error'}). Your repo is fine.</p>
          <Link className="big-button" to="/">Try again</Link>
        </section>
      )}

      {audit?.queue?.lane === 'quick' && audit.status === 'queued' && audit.queue.position > 1 && (
        <p className="notice notice-warn">In line: {audit.queue.position - 1} audit(s) ahead of you.</p>
      )}

      {/* Before the quick result, the live step log holds the result's place; the result then replaces it
          (and a fresh log mounts at the bottom) instead of pushing it down the page: no layout shift. */}
      {!report && audit?.status !== 'failed' && !offline && (
        <StepLog key="live" steps={audit?.steps ?? []} live />
      )}

      {report && audit && audit.status !== 'failed' && (
        <>
          <History audit={audit} />
          <Result audit={audit} />
          {!report.score.gated && (
            <DeepCheck
              audit={audit}
              stats={stats}
              onQueued={() => setTick((t) => t + 1)}
              ready={pending}
              onShow={() => {
                if (!pending) return
                show(pending)
                setPending(null)
                window.scrollTo({ top: 0 })
              }}
            />
          )}
          {!report.score.gated && (
            <RoastCard
              auditId={audit.id}
              repo={report.repo?.full_name ?? audit.repo_url}
              score={report.score.score}
              roast={report.verdict.roast}
              template={report.verdict.source === 'template'}
              delta={report.progress?.delta}
            />
          )}
          {!report.score.gated && report.verdict.source !== 'template' && <ShowcaseToggle key={audit.id} audit={audit} />}
          {!report.score.gated && <SubmissionKit auditId={audit.id} status={audit.status} />}
        </>
      )}

      {audit && (report || audit.status === 'failed') && (
        <StepLog key="log" steps={audit.steps} live={live || ACTIVE_DEEP.includes(audit.phases.deep)} />
      )}
      {audit && (report || audit.status === 'failed') && (
        <RemovalLink auditId={audit.id} onRemoved={() => setRemoved(true)} />
      )}
    </main>
  )
}
