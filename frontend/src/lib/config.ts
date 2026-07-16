/** Runtime config fetched from the backend at startup. The frontend is
 *  otherwise unaware of any deployment-level configuration — every fetch
 *  it issues is to `/...` as if the app lives at the origin's root. The
 *  reverse proxy is responsible for routing those requests to the backend
 *  regardless of where the SPA shell itself is mounted.
 *
 *  The one exception is `homePath`: when deployed at a sub-path
 *  (e.g. `https://host/wiki/`), the browser URL bar shows `/wiki/...`,
 *  so React Router needs that prefix as its `basename` to strip it from
 *  pathnames before matching routes and reapply it when calling
 *  `navigate(...)`. Without it the prefix would be misinterpreted as
 *  part of the doc-id. We get it from `/api/config` rather than baking
 *  it into the build so a single Vite-built bundle works at any
 *  sub-path — the backend (which knows its own `base_url`) tells us.
 */
export interface ServerConfig {
  gracePeriodSeconds: number
  /** Deployment sub-path prefix, e.g. `/wiki`. `''` when mounted at root. */
  homePath: string
}

import { apiUrl } from './backend'

const DEFAULT_CONFIG: ServerConfig = { gracePeriodSeconds: 30, homePath: '' }

let loaded: ServerConfig | null = null
let inflight: Promise<ServerConfig> | null = null

/** Fetch the config from the backend (idempotent — cached after first call).
 *  Failures fall back to defaults rather than blocking the boot; the user
 *  gets a working SPA mounted at root in degraded mode. */
export function loadConfig(): Promise<ServerConfig> {
  if (loaded) return Promise.resolve(loaded)
  if (inflight) return inflight
  inflight = fetch(apiUrl('/api/config'))
    .then((r) => (r.ok ? (r.json() as Promise<ServerConfig>) : DEFAULT_CONFIG))
    .catch(() => DEFAULT_CONFIG)
    .then((c) => {
      loaded = { ...DEFAULT_CONFIG, ...c }
      return loaded
    })
  return inflight
}

/** Synchronous accessor. Safe to call only after `loadConfig()` has
 *  resolved at least once (i.e. from inside the mounted App tree). */
export function getConfig(): ServerConfig {
  if (!loaded) throw new Error('getConfig() called before loadConfig() resolved')
  return loaded
}

/** Non-throwing accessor for the deployment sub-path prefix (e.g. `/wiki`),
 *  or `''` at root and before config has resolved. Unlike `getConfig()` this
 *  is safe to call during the boot window and in tests without a
 *  `loadConfig()` round-trip — it just reports "root" until the real value
 *  lands. Display code that wants to show deployment-qualified paths uses
 *  this; it must NOT be used to build fetch/navigate targets — those stay
 *  origin-rooted / basename-relative (see CLAUDE.md). */
export function getHomePath(): string {
  return loaded?.homePath ?? ''
}
