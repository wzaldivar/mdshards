/** Classification of what the browser can meaningfully DISPLAY for a vault
 *  asset, shared by AssetViewer (to pick the element) and UploadSwitcher (to
 *  decide whether navigating to the asset after upload makes sense at all —
 *  a .zip would just come back as a download, and inside AssetViewer's
 *  sandboxed iframe even that is blocked, leaving a blank page). */

export const IMAGE_EXTS = new Set([
  'png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'avif', 'bmp', 'ico',
])
export const VIDEO_EXTS = new Set(['mp4', 'webm', 'mov', 'm4v', 'ogv'])
export const AUDIO_EXTS = new Set(['mp3', 'wav', 'ogg', 'flac', 'm4a', 'aac'])
/** Extensions browsers reliably render inline inside the viewer's iframe
 *  (mime-typed as displayable by the backend's extension guess). Text-ish
 *  formats that commonly map to application/octet-stream (csv, yaml, toml…)
 *  are deliberately absent: the sandboxed iframe blocks their download
 *  fallback and shows nothing. */
export const DOCUMENT_EXTS = new Set(['pdf', 'txt', 'text', 'log', 'html', 'htm', 'xml', 'json'])

export type AssetKind = 'image' | 'video' | 'audio' | 'other'

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

/** Whether visiting the asset's URL shows the user something (media element
 *  or an iframe the browser renders) rather than a download / blank page. */
export function isViewableAsset(path: string): boolean {
  return kindFor(path) !== 'other' || DOCUMENT_EXTS.has(extOf(path))
}
