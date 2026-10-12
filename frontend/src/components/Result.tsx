import type { Audit, Check, Claim, Report } from '../api'
import { evidenceLink } from '../evidence'
import { CATEGORY_LABELS, CHECK_STATUS, CLAIM_STATUS, scoreTone } from '../labels'
import FeedbackButton from './FeedbackButton'
import JudgePanel from './JudgePanel'

function EvidenceRefs({ refs, report }: { refs: string[]; report: Report }) {
  if (!refs.length) return null
  const repo = report.repo?.full_name
  return (
    <ul className="evidence">
      {refs.map((ref, i) => {
        // report.head_sha is a tree sha, not a commit: link files on the default branch
        const l = evidenceLink(ref, repo, report.repo?.default_branch)
        return (
          <li key={i}>
            {l.href ? (
              <a href={l.href} target="_blank" rel="noopener noreferrer">
                {l.text}
              </a>
            ) : (
              <code>{l.text}</code>
            )}
          </li>
        )
      })}
    </ul>
  )
}

function ScoreBlock({ report, deep }: { report: Report; deep: boolean }) {
  const s = report.score
  // Estimates only come from the deep check; before that (or if the LLM was out) the scoring
  // code fills in neutral defaults, and we say so instead of crediting "the AI".
  const placeholders = s.categories.some((c) =>
    c.items.some((i) => i.estimated && /unavailable|neutral/i.test(i.detail)))
  return (
    <section className="panel score-panel">
      <div className={`score-big tone-${scoreTone(s.score)}`} data-testid="score">
        <span className="score-num">{s.score}</span>
        <span className="score-of">/ 100</span>
      </div>
      <div className="score-side">
        <h1 className="repo-name">{report.repo?.full_name ?? report.repo_url}</h1>
        <div className="badges">
          {deep ? (
            <span className="badge badge-good" data-testid="deep-badge">Deep check complete</span>
          ) : (
            <span className="badge">Quick check</span>
          )}
          {s.scored_max != null && s.scored_max < 100 && (
            <span className="badge badge-muted" data-testid="rescaled-badge">
              Scored on the {s.scored_max} points we could check, scaled to 100
            </span>
          )}
          {s.estimated_points > 0 && (
            <span className="badge badge-muted" data-testid="estimate-badge">
              {placeholders
                ? `${s.estimated_points} pts are neutral placeholders until the deep check`
                : `${s.estimated_points} pts estimated by the AI (capped)`}
            </span>
          )}
        </div>
        <ul className="categories">
          {s.categories.map((c) => {
            const estimated = c.items.some((i) => i.estimated)
            const pct = c.max_points ? Math.round((c.points / c.max_points) * 100) : 0
            return (
              <li key={c.id}>
                <div className="cat-row">
                  <span className="cat-name">
                    {CATEGORY_LABELS[c.id] ?? c.id}
                    {estimated && <span className="tag-estimated">{placeholders ? 'placeholder' : 'estimated'}</span>}
                  </span>
                  <span className="cat-pts">
                    {c.not_scored ? <span className="muted" data-testid="cat-not-scored">not scored</span>
                      : `${c.points} / ${c.max_points}`}
                  </span>
                </div>
                {!c.not_scored && <div className="bar" role="meter" aria-valuenow={c.points} aria-valuemin={0} aria-valuemax={c.max_points}
                     aria-label={CATEGORY_LABELS[c.id] ?? c.id}>
                  <span className={`bar-fill tone-${scoreTone(pct)}`} style={{ width: `${pct}%` }} />
                </div>}
              </li>
            )
          })}
        </ul>
      </div>
    </section>
  )
}

function RoastBlock({ report }: { report: Report }) {
  const v = report.verdict
  const template = v.source === 'template'
  return (
    <section className="panel roast-panel">
      {template && (
        <p className="notice notice-cool" data-testid="template-notice">
          Quick facts mode: the roast oven is cooling, check back later for the full roast.
        </p>
      )}
      <p className="roast" data-testid="roast">
        “{v.roast}”
      </p>
      {!template && v.roast_source === 'template' ? (
        <p className="roast-style" data-testid="fact-only">
          Fact-only roast: the AI's jokes didn't pass our fact check, so you get the facts straight.
        </p>
      ) : (
        v.style && !template && <p className="roast-style">as told by a {v.style}</p>
      )}
      <div className="best">
        <span className="best-label">Best thing about this repo</span>
        <p>{v.best_thing}</p>
      </div>
    </section>
  )
}

function Fixes({ report }: { report: Report }) {
  const fixes = [...report.verdict.fixes].sort((a, b) => b.points - a.points)
  if (!fixes.length) return null
  return (
    <section className="panel">
      <h2 className="panel-title">Fix these first</h2>
      <ol className="fixes">
        {fixes.map((f) => (
          <li key={f.check_id}>
            <span className="fix-pts">+{f.points}</span>
            <div>
              <strong>{f.title}</strong>
              <p>{f.fix}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}

function Claims({ claims, report, auditId }: { claims: Claim[]; report: Report; auditId: string }) {
  if (!claims.length) return null
  const verified = claims.filter((c) => c.status === 'verified').length
  return (
    <section className="panel">
      <h2 className="panel-title">
        README claims on trial <span className="muted">({verified} of {claims.length} backed by evidence)</span>
      </h2>
      <ul className="claims">
        {claims.map((c) => {
          const st = CLAIM_STATUS[c.status]
          return (
            <li key={c.claim_id} className="claim">
              <div className="claim-head">
                <span className={`pill tone-${st.tone}`}>{st.label}</span>
                <span className="claim-text">{c.claim}</span>
              </div>
              {c.reason && <p className="muted small">{c.reason}</p>}
              <EvidenceRefs refs={c.evidence.map((e) => e.ref)} report={report} />
              <FeedbackButton auditId={auditId} checkId={`claim:${c.claim_id}`} />
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function Checks({ checks, report, auditId }: { checks: Check[]; report: Report; auditId: string }) {
  return (
    <section className="panel">
      <h2 className="panel-title">Every check</h2>
      <ul className="checks">
        {checks.map((c) => {
          const st = CHECK_STATUS[c.status] ?? { label: c.status, tone: 'muted' }
          const notScored = c.data?.not_scored === true
          const advice = typeof c.data?.advice === 'string' ? c.data.advice : null
          return (
            <li key={c.id} className="check">
              <div className="claim-head">
                <span className={`pill tone-${st.tone}`}>{st.label}</span>
                <span className="claim-text">{c.title}</span>
                {notScored && <span className="tag-estimated" data-testid="not-scored">not scored</span>}
              </div>
              <p className="muted small">{c.detail}</p>
              {advice && <p className="small check-advice">{advice}</p>}
              <EvidenceRefs refs={c.evidence.filter((e) => /^https?:|:\d+$/.test(e)).slice(0, 4)} report={report} />
              <FeedbackButton auditId={auditId} checkId={c.id} />
            </li>
          )
        })}
      </ul>
    </section>
  )
}

export function RepoUnavailable({ report, errorKind }: { report: Report; errorKind: string | null }) {
  const detail = report.checks.find((c) => c.id === 'repo_public')?.detail ?? report.score.gate_reason ?? ''
  // Only say "private" when GitHub told us so; a 404 can mean missing OR private and we don't guess.
  const isPrivate = errorKind === 'private'
  return (
    <section className="panel error-panel" data-testid="repo-unavailable">
      <h1 className="headline">{isPrivate ? 'This repo is private.' : "We can't find this repo."}</h1>
      <p className="lede">
        {isPrivate
          ? "Judges can't open it either. Make it public before you submit, then try again."
          : "GitHub says it doesn't exist. Check the URL for typos. Private repos look exactly like this to " +
            'outsiders too, so if it is private, make it public first.'}
      </p>
      <p className="muted small">{detail}</p>
    </section>
  )
}

export default function Result({ audit }: { audit: Audit }) {
  const report = audit.result!
  if (report.score.gated) {
    const repoStep = audit.steps.find((st) => st.name === 'github.get_repo')
    return <RepoUnavailable report={report} errorKind={repoStep?.error_kind ?? null} />
  }
  const deep = audit.status === 'complete'
  const injection = report.agent?.injection?.detected || report.checks.some((c) => c.id === 'prompt_injection' && c.status === 'fail')
  return (
    <>
      <ScoreBlock report={report} deep={deep} />
      {audit.features?.judge_panel && <JudgePanel auditId={audit.id} status={audit.status} />}
      {injection && (
        <p className="notice notice-bad">
          This README tries to instruct the judge (prompt injection). It was ignored and flagged; it can't change the score.
        </p>
      )}
      <RoastBlock report={report} />
      <Fixes report={report} />
      {report.agent && <Claims claims={report.agent.claims} report={report} auditId={audit.id} />}
      <Checks checks={report.checks} report={report} auditId={audit.id} />
    </>
  )
}
