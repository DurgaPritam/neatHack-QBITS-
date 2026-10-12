import { useEffect, useState } from 'react'
import { countdown } from '../labels'

// Ticks every second until the neatHack deadline; fixed-width digits so the line never moves.
export default function Countdown() {
  const [now, setNow] = useState(() => Date.now())
  const left = countdown(now)
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [])
  if (!left)
    return (
      <p className="deadline deadline-closed" data-testid="deadline">
        Submissions closed
      </p>
    )
  return (
    <p className="deadline" data-testid="deadline">
      ⏳ Submissions close in <span className="deadline-time">{left}</span>
    </p>
  )
}
