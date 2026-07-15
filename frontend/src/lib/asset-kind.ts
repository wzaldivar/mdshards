/** Classification of what the browser can meaningfully DISPLAY for a vault
 *  asset, used by AssetViewer to pick the element and sandboxing. The
 *  guiding rule: prefer the browser's DEFAULT
 *  handling — an unsandboxed iframe renders whatever the browser can and
 *  natively downloads whatever it can't. Sandboxing is applied only where
 *  it buys real protection (script-capable types), because a sandbox also
 *  blocks the PDF viewer plugin and silently swallows download fallbacks. */

export const IMAGE_EXTS = new Set([
  'png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'avif', 'bmp', 'ico',
])
export const VIDEO_EXTS = new Set(['mp4', 'webm', 'mov', 'm4v', 'ogv'])
export const AUDIO_EXTS = new Set(['mp3', 'wav', 'ogg', 'flac', 'm4a', 'aac'])

/** Types that can execute script in the SPA's origin when framed or
 *  navigated same-origin — the vault takes external writes
 *  (Syncthing/Obsidian), so these are the XSS vector and the ONLY types
 *  that need the iframe sandbox (and the backend's `CSP: sandbox`, see
 *  pages.py). svg is listed for completeness though the viewer renders it
 *  via <img>, which never scripts. */
export const SCRIPTABLE_EXTS = new Set([
  'html', 'htm', 'xhtml', 'xht', 'shtml', 'xml', 'svg', 'mht', 'mhtml',
])

/** Known bundle/binary formats no browser renders inline. The viewer skips
 *  the iframe and goes straight to the download panel — the download IS the
 *  browser default for these; the panel just narrates it. */
export const ARCHIVE_EXTS = new Set([
  'zip', 'tar', 'gz', 'tgz', 'bz2', 'xz', '7z', 'rar',
  'dmg', 'iso', 'exe', 'msi', 'bin', 'apk', 'jar', 'war',
  'docx', 'xlsx', 'pptx', 'odt', 'ods', 'odp',
])

export type AssetKind = 'image' | 'video' | 'audio' | 'other'

/** How the viewer should frame a non-media asset. */
export type FrameMode = 'sandboxed' | 'plain' | 'download'

export function extOf(path: string): string {
  const i = path.lastIndexOf('.')
  return i === -1 ? '' : path.slice(i + 1).toLowerCase()
}

export function kindFor(path: string): AssetKind {
  const ext = extOf(path)
  if (IMAGE_EXTS.has(ext)) return 'image'
  if (VIDEO_EXTS.has(ext)) return 'video'
  if (AUDIO_EXTS.has(ext)) return 'audio'
  return 'other'
}

export function frameModeFor(path: string): FrameMode {
  const ext = extOf(path)
  if (SCRIPTABLE_EXTS.has(ext)) return 'sandboxed'
  if (ARCHIVE_EXTS.has(ext)) return 'download'
  return 'plain'
}
