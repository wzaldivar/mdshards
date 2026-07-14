/** Where the backend lives, from the bundle's point of view.
 *
 * ONE env var, `VITE_BACKEND_HOST`, covers every deployment shape — what it
 * does depends on which command saw it. Unset at build time (modes 1 and 2):
 * this constant is EMPTY and every URL the bundle emits is origin-rooted
 * (`/api/...`, `/ws/...`, `/<asset>`); whatever serves the bundle (uvicorn
 * itself, or `VITE_BACKEND_HOST=<url> npm run preview`, where the same var
 * is only a runtime proxy target) routes them to the backend — no rebuild is
 * ever needed to redeploy.
 *
 * Set at BUILD time (mode 3, static host, at your own risk): Vite bakes the
 * origin in here and the bundle addresses the backend directly. Every
 * backend hostname change requires a rebuild, and satisfying the backend's
 * origin guard (Sec-Fetch-Site for /api, Origin↔Host equality for /ws)
 * across origins is the deployer's problem. See README "Deployment".
 */
/** Drop trailing slashes so `BACKEND_HOST + '/api/...'` is clean. A plain
 *  scan, not a regex — `/\/+$/` trips SonarCloud's super-linear-backtracking
 *  check (S8786), and a loop is O(n) with zero backtracking. */
function stripTrailingSlashes(s: string): string {
  let end = s.length
  while (end > 0 && s[end - 1] === '/') end--
  return s.slice(0, end)
}

export const BACKEND_HOST = stripTrailingSlashes(
  (import.meta.env.VITE_BACKEND_HOST as string | undefined) ?? '',
)

/** Sub-path mount prefix (`/notes`), or '' at a root mount. The backend
 *  injects `<meta name="mdshards-home-path">` into the shell it serves when
 *  BASE_URL is set (see backend pages.py `_prefix_shell`) — reading it here,
 *  before the first fetch, is what solves the bootstrap problem of needing
 *  `/api/config` to learn the prefix that `/api/config` itself lives under.
 *  SERVE-time injection, so the prefix is still never baked into the bundle.
 *  Empty in dev and previews (Vite serves its own shell, no meta) and on
 *  static hosts (mode 3 serves the unmodified dist/ index.html). Read per
 *  call: a DOM query is trivial next to the network round-trip it precedes,
 *  and it keeps tests free of module-reload gymnastics. */
function homePathPrefix(): string {
  if (typeof document === 'undefined') return ''
  const meta = document.querySelector('meta[name="mdshards-home-path"]')
  return meta?.getAttribute('content') ?? ''
}

/** Prefix an origin-rooted backend path (`/api/...`, `/pic.png`) with the
 *  configured backend origin and the sub-path mount prefix. Pass-through
 *  when neither is configured. */
export function backendUrl(path: string): string {
  return BACKEND_HOST + homePathPrefix() + path
}

/** WebSocket server URL (no room suffix). Derived from BACKEND_HOST when
 *  baked, else from the page's own origin, carrying the sub-path prefix
 *  either way; the server/proxy in front forwards `<prefix>/ws/...` to the
 *  backend. */
export function backendWsUrl(): string {
  if (BACKEND_HOST) return BACKEND_HOST.replace(/^http/, 'ws') + homePathPrefix() + '/ws'
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}${homePathPrefix()}/ws`
}
