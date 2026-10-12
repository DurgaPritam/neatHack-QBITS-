// Typed client for the PreJudge API. Network failures and HTTP errors are kept apart so the
// UI can tell "can't reach the server" from "the server said no".

export type Status = 'pass' | 'warn' | 'fail' | 'unverified'

export interface Step {
  name: string
  status: 'ok' | 'failed' | 'skipped'
  detail: string
  error_kind: string | null
  duration_ms: number
}

export interface Check {
  id: string
  category: string
  title: string
  status: Status
  detail: string
  evidence: string[]
  data?: Record<string, unknown>
}

export interface ScoreItem {
  id: string
  title: string
  status: string
  detail: string
  credit: number
  points: number
  max_points: number
  estimated: boolean
}

export interface Category {
  id: string
  weight: number
  max_points: number
  points: number
  not_scored?: boolean // nothing in it could be checked: left out, total rescaled
  items: ScoreItem[]
}

export interface Score {
  score: number
  max: number
  gated: boolean
  gate_reason: string | null
  estimated_points: number
  scored_max?: number // < 100 when a category was left out
  categories: Category[]
}

export interface Fix {
  check_id: string
  title: string
  points: number
  fix: string
}

export interface Verdict {
  roast: string
  fixes: Fix[]
  best_thing: string
  style?: string
  source: 'llm' | 'template'
  roast_source?: 'llm' | 'template' // template = the AI's roast failed the fact check
}

export interface Evidence {
  ref: string
  note?: string
}

export interface Claim {
  claim_id: string
  claim: string
  quote?: string
  category?: string
  status: 'verified' | 'unverified' | 'contradicted'
  evidence: Evidence[]
  reason: string
}

export interface Report {
  audit_id: string
  repo_url: string
  repo: { full_name: string; default_branch: string; stars?: number } | null
  head_sha?: string
  checks: Check[]
  score: Score
  verdict: Verdict
  phase: 'quick' | 'complete'
  agent?: {
    claims: Claim[]
    estimates: Record<string, { score: number; evidence: string[]; reason: string }>
    injection: { detected: boolean; deterministic?: string[]; reported_by_llm?: string[] }
  }
  timing_ms?: Record<string, number>
  reuse?: Reuse
  progress?: Progress
}

export interface Reuse {
  from: string
  checked_at: string
  tokens_saved: number
  deep: boolean
}

export interface Progress {
  previous_audit_id: string
  previous_at: string
  previous_score: number
  score: number
  delta: number
  text: string
  fixed: string[]
  regressed: string[]
}

export interface Percentiles {
  cohort_size: number
  beats_pct: number
  text: string
  checks: { check_id: string; pct: number; passed: boolean; text: string }[]
}

export interface QueueInfo {
  lane: 'quick' | 'deep'
  position: number
  estimated_wait_s: number
  waiting_for_budget: boolean
}

export interface Audit {
  id: string
  repo_url: string
  status: 'queued' | 'quick_ready' | 'complete' | 'failed'
  phases: { quick: string; deep: string }
  queue: QueueInfo | null
  cached: boolean
  steps: Step[]
  result: Report | null
  percentiles?: Percentiles | null
  showcase?: boolean
  features?: { demo_script?: boolean; judge_panel?: boolean }
  sponsors?: SponsorRow[] | null
  glass_box?: GlassBox | null
  error: string | null
}

export interface Kit {
  post: { text: string; length: number; limit: number; over: boolean; blanks: number }
  evidence_md: string
  badge: { url: string; markdown: string }
}

export interface GlassStep {
  name: string
  status: string
  ms: number
  tokens: number
  model: string | null
  cost_usd: number
  kind: 'retry' | 'fallback' | 'wait' | 'failed' | null
  wait_s?: number | null
  to_model?: string | null
  note?: string | null
}

export interface GlassBox {
  steps: GlassStep[]
  phases: Record<string, { tokens: number; calls: number; failed_calls: number; cost_usd: number; ms: number | null }>
  totals: { tokens: number; cost_usd: number; ms: number; retries: number; fallbacks: number; quota_waits: number }
  pricing: string
  traced_with: string
}

export interface SponsorRow {
  tool: string
  level: number
  label: string
  why: string
  next_step: string
  evidence: string[]
}

export interface DemoScene {
  id: string
  start: string
  end: string
  seconds: number
  topic: string
  show: string
  say: string
  todo: boolean
}

export interface DemoScript {
  source: 'llm' | 'template'
  total: string
  scenes: DemoScene[]
  todos: number
  text: string
}

export interface JudgePanel {
  source: 'llm' | 'template'
  judges: { id: string; title: string; praise: string; fix: string }[]
}

export interface Stats {
  total_audits: number
  completed_audits: number
  budget_state: 'normal' | 'busy' | 'cooling'
  deep_queue: number
  deep_wait_s: number
  llm_mode: string
}

export interface Example {
  id: string
  repo: string
  score: number | null
  roast: string | null
  style: string | null
  example?: boolean
}

export interface AdminOverview {
  budget: {
    public_available: boolean
    public_tokens: { used: number; cap: number }
    reserve_pct: number
    state: string
    models: Record<string, { used: number; limit: number; public_limit: number; ok: boolean }>
  }
  deep: { used_today: number; daily_cap: number; per_repo_cap: number; by_repo: { repo: string; count: number }[] }
  queue: { quick: number; deep: number; deep_max: number; waiting_budget: boolean }
  reuse: { tokens_saved_today: number; tokens_saved_total: number; reused_today: number }
  limits: {
    recent: { at: number; kind: string; ip: string | null; repo: string | null }[]
    by_ip: { key: string; hits: number }[]
    by_repo: { key: string; hits: number }[]
    today: Record<string, number>
  }
  projects: {
    repo_key: string; repo_url: string; first_seen: string; last_audit_at: string | null; last_audit_id: string | null
    audit_count: number; deep_count: number; latest_score: number | null; best_score: number | null
    is_hackathon_repo: number
  }[]
  recent_audits: {
    id: string; repo_key: string; status: string; phase_deep: string; run_kind: string
    cached_from: string | null; hidden: number; created_at: string; score: number | null; tokens: number | null
  }[]
  feedback: { id: number; audit_id: string; repo_url: string; check_id: string; note: string; created_at: string }[]
  metrics: { days: Record<string, number | string>[]; totals: Record<string, number>; roasts?: number; unique_repos?: number }
  llm_mode: string
}

export class ApiError extends Error {
  status: number
  network: boolean
  constructor(message: string, status = 0, network = false) {
    super(message)
    this.status = status
    this.network = network
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    })
  } catch {
    throw new ApiError("Can't reach PreJudge right now.", 0, true)
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : detail
    } catch {
      /* not JSON */
    }
    throw new ApiError(detail, res.status)
  }
  return res.json() as Promise<T>
}

export const api = {
  createAudit: (repo_url: string) =>
    request<{ id: string; status: string; cached: boolean }>('/api/audits', {
      method: 'POST',
      body: JSON.stringify({ repo_url }),
    }),
  getAudit: (id: string) => request<Audit>(`/api/audits/${encodeURIComponent(id)}`),
  requestDeep: (id: string) =>
    request<{ status: string; queue: QueueInfo | null }>(`/api/audits/${encodeURIComponent(id)}/deep`, {
      method: 'POST',
    }),
  feedback: (id: string, check_id: string, note: string) =>
    request<{ ok: boolean }>(`/api/audits/${encodeURIComponent(id)}/feedback`, {
      method: 'POST',
      body: JSON.stringify({ check_id, is_wrong: true, note }),
    }),
  requestRemoval: (id: string, reason: string) =>
    request<{ ok: boolean; hidden: boolean }>(`/api/audits/${encodeURIComponent(id)}/removal`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),
  stats: () => request<Stats>('/api/stats'),
  // Admin: the token lives only in memory (React state) and is sent per request.
  adminOverview: (token: string) =>
    request<AdminOverview>('/api/admin/overview', { headers: { 'X-Admin-Token': token } }),
  examples: () => request<Example[]>('/api/examples'),
  showcase: () => request<Example[]>('/api/showcase'),
  kit: (id: string) => request<Kit>(`/api/audits/${encodeURIComponent(id)}/kit`),
  demoScript: (id: string) => request<DemoScript>(`/api/audits/${encodeURIComponent(id)}/demo-script`),
  judgePanel: (id: string) => request<JudgePanel>(`/api/audits/${encodeURIComponent(id)}/judge-panel`),
  setShowcase: (id: string, show: boolean) =>
    request<{ ok: boolean; showcase: boolean }>(`/api/audits/${encodeURIComponent(id)}/showcase`, {
      method: 'POST',
      body: JSON.stringify({ show }),
    }),
}

// A bare per-day counter (no cookies, nothing about the viewer). Never blocks or throws.
export function countEvent(name: 'card_download' | 'share_x'): void {
  try {
    fetch('/api/events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
      keepalive: true,
    }).catch(() => {})
  } catch {
    /* counting is best-effort */
  }
}

const GITHUB_URL = /^(https?:\/\/)?(www\.)?github\.com\/[A-Za-z0-9-]+\/[A-Za-z0-9._-]+\/?(\.git)?$|^[A-Za-z0-9-]+\/[A-Za-z0-9._-]+$/

export function looksLikeRepo(input: string): boolean {
  return GITHUB_URL.test(input.trim())
}

export function shareUrl(id: string): string {
  const base = (import.meta.env.VITE_SHARE_BASE as string | undefined) ?? window.location.origin
  return `${base.replace(/\/$/, '')}/r/${id}`
}
