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
  items: ScoreItem[]
}

export interface Score {
  score: number
  max: number
  gated: boolean
  gate_reason: string | null
  estimated_points: number
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
  error: string | null
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
  examples: () => request<Example[]>('/api/examples'),
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
