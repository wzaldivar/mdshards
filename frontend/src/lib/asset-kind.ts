/** Classification of what the browser can meaningfully DISPLAY for a vault
 *  asset, shared by AssetViewer (to pick the element and sandboxing) and
 *  UploadSwitcher (to decide whether navigating to the asset after upload
 *  makes sense at all). The guiding rule: prefer the browser's DEFAULT
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

/** Text-ish extensions whose mime guess is text/* in practice — every
 *  browser renders them inline, so auto-navigating to them after upload is
 *  guaranteed to show something. Formats with browser-dependent handling
 *  (csv, yaml, toml → often application/octet-stream) are deliberately
 *  absent: explicit navigation still gives them browser-default treatment
 *  via the plain iframe, but upload doesn't auto-navigate into a possible
 *  surprise download. (No `ts` — mime-guessed as MPEG transport stream.) */
const TEXT_EXTS = new Set([
  'txt', 'text', 'log', 'json', 'js', 'mjs', 'cjs', 'css',
  'py', 'sh', 'rb', 'pl', 'c', 'h', 'java', 'sql',
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

/** Whether visiting the asset's URL is guaranteed to SHOW something (media,
 *  a rendered document, readable text) rather than kick off a download.
 *  Gates the post-upload auto-navigation. */
export function isViewableAsset(path: string): boolean {
  const ext = extOf(path)
  return (
    kindFor(path) !== 'other' ||
    SCRIPTABLE_EXTS.has(ext) ||
    TEXT_EXTS.has(ext) ||
    ext === 'pdf'
  )
}
