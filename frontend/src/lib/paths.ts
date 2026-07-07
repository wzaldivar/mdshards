/**
 * Mirror the backend vault path rules client-side, so the UI can refuse
 * invalid paths before sending them. Keep this in lock-step with
 * `backend/app/vault.py`.
 */

export type PathRejection = string

export function validateVaultPath(path: string): PathRejection | null {
  if (path === '') return null
  if (path.includes('\0')) return 'null byte in path'
  if (path.includes(' ')) return 'spaces are not allowed'
  const trimmed = path.replace(/^\/+/, '')
  if (trimmed === '') return null
  const segments = trimmed.split('/')
  for (const segment of segments) {
    if (segment === '' || segment === '.' || segment === '..') {
      return `illegal path segment: '${segment}'`
    }
    if (segment.includes('\\')) return 'backslash in path segment'
  }
  return null
}
