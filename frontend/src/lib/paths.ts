/**
 * Mirror the backend vault path rules client-side, so the UI can refuse
 * invalid paths before sending them. Keep this in lock-step with
 * `backend/app/vault.py`.
 */

/** The one reserved top-level name — the mdshards app-surface namespace
 *  (`/_mdshards/*`: API, WebSocket, bundle, favicon). A vault path whose first
 *  segment is this would collide with the app subtree, so it's refused up
 *  front. Keep in lockstep with `_RESERVED_SEGMENT` in backend/app/vault.py
 *  and APP_PREFIX in lib/backend.ts. */
const RESERVED_SEGMENT = '_mdshards'

export function validateVaultPath(path: string): string | null {
  if (path === '') return null
  if (path.includes('\0')) return 'null byte in path'
  // Spaces are allowed — stored literally on disk, percent-encoded only when
  // a path is placed into a URL (see `encodePathToUrl`).
  const trimmed = path.replace(/^\/+/, '')
  if (trimmed === '') return null
  const segments = trimmed.split('/')
  if (segments[0] === RESERVED_SEGMENT) {
    return `'${RESERVED_SEGMENT}' is a reserved top-level name (mdshards app namespace)`
  }
  for (const segment of segments) {
    if (segment === '' || segment === '.' || segment === '..') {
      return `illegal path segment: '${segment}'`
    }
    if (segment.includes('\\')) return 'backslash in path segment'
  }
  return null
}

/**
 * Turn a raw vault path (which may contain spaces or other reserved chars)
 * into a URL path suitable for navigation, a fetch URL, a WebSocket room, or
 * an asset `src`. Each `/`-separated segment is percent-encoded; the
 * separators are preserved. The inverse is automatic: react-router decodes
 * splat params and the backend decodes path params, so internal code always
 * works with the raw form and only encodes at the URL boundary.
 */
export function encodePathToUrl(path: string): string {
  return path.split('/').map(encodeURIComponent).join('/')
}
