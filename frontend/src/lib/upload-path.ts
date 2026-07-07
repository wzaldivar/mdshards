/**
 * Decide the final vault path for an uploaded file, given:
 *   - the user-typed target path (no extension required), and
 *   - the source file's original filename.
 *
 * Rule: whatever the user typed wins for the basename + extension. The only
 * thing we fill in is a missing extension — if the typed path has none, the
 * source filename's extension is appended (so `foo/my_dog` + `cat.jpeg`
 * becomes `foo/my_dog.jpeg`, and `foo/note` + `draft.md` becomes
 * `foo/note.md`).
 *
 * The md-vs-asset dispatch is decided downstream from the **source** file's
 * extension, not from this path — see `UploadSwitcher`. So an md source
 * typed as `foo.jpeg` keeps the typed `foo.jpeg`; the on-disk filename
 * becomes `foo.jpeg.md` because the md upload path appends `.md`.
 *
 * Returns `null` if `typed` is empty.
 */
export function finalizeUploadPath(typed: string, sourceFilename: string): string | null {
  const cleaned = typed.replace(/^\/+/, '').trim()
  if (!cleaned) return null

  const typedExt = extractExtension(cleaned)
  if (typedExt) return cleaned
  const sourceExt = extractExtension(sourceFilename)
  if (!sourceExt) return cleaned
  return cleaned + '.' + sourceExt
}

function extractExtension(p: string): string {
  const lastSlash = p.lastIndexOf('/')
  const lastDot = p.lastIndexOf('.')
  if (lastDot <= lastSlash) return ''
  if (lastDot === p.length - 1) return ''
  return p.slice(lastDot + 1).toLowerCase()
}

/** Whether the resolved upload path is a markdown file. */
export function isMarkdownPath(path: string): boolean {
  return extractExtension(path) === 'md'
}

/** Strip whitespace from a filename. Vault paths reject spaces (validated
 *  both client- and server-side), so the upload modal prefills the target
 *  path via this helper to keep the prefill immediately submittable. Dots
 *  inside the basename are preserved — the backend disambiguates between
 *  md and asset paths by file existence (see `/api/resolve`), so URLs like
 *  `/notes/my.weekly` resolve to the md note `vault/notes/my.weekly.md`. */
export function normalizeFilename(name: string): string {
  return name.replace(/\s+/g, '')
}
