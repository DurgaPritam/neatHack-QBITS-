// Human wording for step names, rubric categories and statuses.

const STEP_LABELS: [RegExp, string][] = [
  [/^parse_url$/, 'Reading the repo URL'],
  [/^github\.get_repo$/, 'Opening the repo'],
  [/^github\.get_readme/, 'Reading the README'],
  [/^github\.get_tree$/, 'Listing every file'],
  [/^github\.get_dependency_files$/, 'Checking dependency files'],
  [/^github\.get_commits$/, 'Checking commit dates against the hackathon window'],
  [/^links\.check$/, 'Clicking every README link'],
  [/^video\.duration$/, 'Timing the demo video'],
  [/^llm\.quick_verdict$/, 'Writing the roast'],
  [/^quick_verdict\.template_fallback$/, 'Quick facts mode: roast from the checks alone'],
  [/^github\.download_tarball$/, 'Downloading a read-only copy of the code'],
  [/^verify\.presearch$/, 'Searching the code for every claim'],
  [/^llm\.claims/, 'Pulling claims out of the README'],
  [/^llm\.verify\.final/, 'Deciding each claim'],
  [/^llm\.verify/, 'Judging claims'],
  [/^tool\.search_repo$/, 'Agent searched the code'],
  [/^tool\.read_file$/, 'Agent read a file'],
  [/^tool\.list_files$/, 'Agent listed a folder'],
  [/^tool\.get_commits$/, 'Agent checked commits'],
  [/^tool\.check_link$/, 'Agent checked a link'],
  [/^llm\.verdict/, 'Rewriting the verdict with the evidence'],
  [/\.fallback$/, 'Switched to another model'],
  [/wait_for_quota$/, 'Waiting for LLM quota'],
  [/roast_rejected$/, 'Roast failed the fact check, rewriting'],
  [/roast_template$/, 'Using a fact-only roast'],
  [/template_fallback$/, 'Quick facts mode'],
  [/budget_exhausted$/, 'Tool budget used up, deciding now'],
  [/^github\.get_entire_refs$/, 'Looking for Entire checkpoints'],
  [/^verify\.failure_recovery$/, 'Checking for a failure-and-recovery run'],
  [/^deep\.rebuild_context$/, 'Re-reading the repo'],
  [/^deep\.waiting_budget$/, 'Waiting for judge-model budget'],
  [/crashed$/, 'Something broke'],
]

export function stepLabel(name: string): string {
  for (const [rx, label] of STEP_LABELS) if (rx.test(name)) return label
  return name.replace(/[._]/g, ' ')
}

// The same step can run several times (each agent tool call, each judging round). Number
// repeats instead of showing identical lines: "Agent searched the code (2 of 5)".
const ROUND_LABELS: Record<string, (n: number, total: number) => string> = {
  'Judging claims': (n, total) => `Judging claims, round ${n} of ${total}`,
}

export function numberedLabels(names: string[]): string[] {
  const labels = names.map(stepLabel)
  const totals = new Map<string, number>()
  for (const l of labels) totals.set(l, (totals.get(l) ?? 0) + 1)
  const seen = new Map<string, number>()
  return labels.map((l) => {
    const total = totals.get(l) ?? 1
    if (total < 2) return l
    const n = (seen.get(l) ?? 0) + 1
    seen.set(l, n)
    return ROUND_LABELS[l] ? ROUND_LABELS[l](n, total) : `${l} (${n} of ${total})`
  })
}

export const CATEGORY_LABELS: Record<string, string> = {
  agent: 'Agent',
  tools: 'neatlogs + Entire + cfo.ai',
  demo_video: 'Demo video',
  building_in_public: 'Building in public',
  usefulness: 'Usefulness',
}

export const CHECK_STATUS: Record<string, { label: string; tone: string }> = {
  pass: { label: 'pass', tone: 'good' },
  warn: { label: 'partial', tone: 'warn' },
  fail: { label: 'fail', tone: 'bad' },
  unverified: { label: 'unknown', tone: 'muted' },
}

export const CLAIM_STATUS: Record<string, { label: string; tone: string }> = {
  verified: { label: 'verified', tone: 'good' },
  unverified: { label: 'no evidence', tone: 'muted' },
  contradicted: { label: 'contradicted', tone: 'bad' },
}

export function scoreTone(score: number | null | undefined): string {
  if (score == null) return 'muted'
  return score >= 70 ? 'good' : score >= 40 ? 'warn' : 'bad'
}

export function formatWait(seconds: number): string {
  if (seconds < 60) return `~${Math.max(5, Math.round(seconds / 5) * 5)}s`
  return `~${Math.round(seconds / 60)} min`
}
