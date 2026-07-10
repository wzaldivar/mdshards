/** Where the backend lives, from the bundle's point of view.
 *
 * Default (deployment modes 1 and 2): EMPTY — every URL the bundle emits is
 * origin-rooted (`/api/...`, `/ws/...`, `/<asset>`), and whatever serves the
 * bundle (uvicorn itself, or the Vite preview server's BACKEND_HOST proxy)
 * routes them to the backend. No rebuild is ever needed to redeploy.
 *
 * Deployment mode 3 (static host, at your own risk): bake a backend origin
 * into the bundle at BUILD time with `VITE_BACKEND_HOST=https://api.host` —
 * the bundle then addresses the backend directly. Every backend hostname
 * change requires a rebuild, and satisfying the backend's origin guard
 * (Sec-Fetch-Site for /api, Origin↔Host equality for /ws) across origins is
 * the deployer's problem. See README "Deployment".
 */
export const BACKEND_HOST = ((import.meta.env.VITE_BACKEND_HOST as string | undefined) ?? '')
  // Normalize away a trailing slash so `BACKEND_HOST + '/api/...'` is clean.
  .replace(/\/+$/, '')

/** Prefix an origin-rooted backend path (`/api/...`, `/pic.png`) with the
 *  configured backend origin. Pass-through when none is configured. */
export function backendUrl(path: string): string {
  return BACKEND_HOST + path
}

/** WebSocket server URL (no room suffix). Derived from BACKEND_HOST when
 *  baked, else from the page's own origin — WebSockets don't go through any
 *  deployment-prefix layer; in modes 1/2 the server/proxy in front forwards
 *  `/ws/...` to the backend. */
export function backendWsUrl(): string {
  if (BACKEND_HOST) return BACKEND_HOST.replace(/^http/, 'ws') + '/ws'
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/ws`
}
