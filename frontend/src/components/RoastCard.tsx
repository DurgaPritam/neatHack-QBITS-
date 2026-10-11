import { toPng } from 'html-to-image'
import { useRef, useState } from 'react'
import { countEvent, shareUrl } from '../api'
import { scoreTone } from '../labels'

interface Props {
  auditId: string
  repo: string
  score: number | null
  roast: string
  template: boolean
}

const SITE = (import.meta.env.VITE_SITE_NAME as string | undefined) ?? window.location.host

// 1200x630 card rendered at full size and shown scaled; html-to-image exports the full-size node.
export default function RoastCard({ auditId, repo, score, roast, template }: Props) {
  const cardRef = useRef<HTMLDivElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const download = async () => {
    if (!cardRef.current) return
    setBusy(true)
    setError(null)
    try {
      const url = await toPng(cardRef.current, { width: 1200, height: 630, pixelRatio: 1, cacheBust: true })
      const a = document.createElement('a')
      a.href = url
      a.download = `prejudge-${repo.replace('/', '-')}.png`
      a.click()
      countEvent('card_download')
    } catch {
      setError("Couldn't make the image. Try again?")
    } finally {
      setBusy(false)
    }
  }

  const short = roast.length > 150 ? roast.slice(0, 147).trimEnd() + '…' : roast
  const tweet = `PreJudge roasted ${repo}: ${score ?? '?'}/100 🔥 "${short}" #neatHack`
  const xHref = `https://twitter.com/intent/tweet?text=${encodeURIComponent(tweet)}&url=${encodeURIComponent(shareUrl(auditId))}`

  return (
    <section className="panel card-panel">
      <h2 className="panel-title">Roast card</h2>
      <div className="card-frame">
        <div className="card-scale">
          <div className="roast-card" ref={cardRef} data-testid="roast-card">
            <div className="rc-stripe" />
            <div className="rc-head">
              <span className="rc-brand">PREJUDGE</span>
              <span className="rc-sub">roasted before the judges</span>
              <span className="rc-tag">#neatHack</span>
            </div>
            <div className="rc-body">
              <div className={`rc-score tone-${scoreTone(score)}`}>
                <span className="rc-num">{score ?? '?'}</span>
                <span className="rc-of">/ 100</span>
              </div>
              <p className={`rc-roast ${roast.length > 260 ? 'rc-roast-long' : ''}`}>“{roast}”</p>
            </div>
            {template && <div className="rc-note">quick facts mode: full roast coming later</div>}
            <div className="rc-foot">
              <span className="rc-repo">{repo}</span>
              <span className="rc-site">{SITE}</span>
            </div>
          </div>
        </div>
      </div>
      <div className="button-row">
        <button className="big-button" onClick={download} disabled={busy}>
          {busy ? 'Rendering…' : 'Download PNG'}
        </button>
        <a className="big-button x-button" href={xHref} target="_blank" rel="noopener noreferrer"
           onClick={() => countEvent('share_x')}>
          Share on X
        </a>
      </div>
      {error && <p className="inline-error">{error}</p>}
    </section>
  )
}
