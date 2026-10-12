import type { SponsorRow } from '../api'

const NAMES = ['mentioned', 'installed / linked', 'evidence shown', 'used to improve']

// Sponsor Depth Scorecard: levels 1-4 per tool, from the checks only (lower level when unsure).
export default function SponsorScorecard({ rows }: { rows: SponsorRow[] }) {
  return (
    <section className="panel sponsor-panel" data-testid="sponsors">
      <h2 className="panel-title">Sponsor depth</h2>
      <p className="muted small sponsor-key">1 mentioned · 2 installed/linked · 3 evidence shown · 4 used to improve</p>
      <ul className="sponsor-rows">
        {rows.map((r) => (
          <li key={r.tool} className="sponsor-row" data-testid="sponsor">
            <div className="sponsor-head">
              <strong className="sponsor-tool">{r.tool}</strong>
              <span className="sponsor-pips" role="meter" aria-valuenow={r.level} aria-valuemin={0} aria-valuemax={4}
                    aria-label={`${r.tool} level ${r.level} of 4`}>
                {[1, 2, 3, 4].map((n) => (
                  <span key={n} className={n <= r.level ? 'pip pip-on' : 'pip'} title={NAMES[n - 1]} />
                ))}
              </span>
              <span className="sponsor-level">Level {r.level}: {r.label}</span>
            </div>
            <p className="sponsor-why muted small">{r.why}</p>
            <p className="sponsor-next small">Next: {r.next_step}</p>
          </li>
        ))}
      </ul>
    </section>
  )
}
