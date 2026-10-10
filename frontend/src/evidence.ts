// Turn evidence refs ("src/agent.py:42", "a1b2c3d4e5f6", "https://...") into links.

export interface EvidenceLink {
  text: string
  href: string | null
}

export function evidenceLink(ref: string, repo: string | undefined, branch: string | undefined): EvidenceLink {
  const r = ref.trim()
  if (/^https?:\/\//i.test(r)) return { text: r, href: r }
  if (!repo) return { text: r, href: null }
  if (/^[0-9a-f]{7,40}$/i.test(r)) return { text: r.slice(0, 12), href: `https://github.com/${repo}/commit/${r}` }
  const m = r.match(/^(.+?)(?::(\d+)(?:-(\d+))?)?$/)
  if (!m || !m[1].includes('.') && !m[1].includes('/')) return { text: r, href: null }
  const [, path, from, to] = m
  const anchor = from ? `#L${from}${to ? `-L${to}` : ''}` : ''
  return { text: r, href: `https://github.com/${repo}/blob/${branch || 'HEAD'}/${path}${anchor}` }
}
