import { formatWait } from '../labels'

export default function BudgetBanner({ state, waitS }: { state: 'normal' | 'busy' | 'cooling'; waitS: number }) {
  if (state === 'normal') return null
  if (state === 'cooling')
    return (
      <p className="notice notice-cool" data-testid="budget-banner">
        The roast oven is cooling (our AI budget for today is used up). You'll get quick facts now and the full
        roast later.
      </p>
    )
  return (
    <p className="notice notice-warn" data-testid="budget-banner">
      Busy right now: deep checks are queued ({formatWait(waitS)}). Quick results are still instant.
    </p>
  )
}
