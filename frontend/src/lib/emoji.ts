/** Lazy access to the gemoji dataset (GitHub's emoji names, ~1900 entries).
 *
 *  The package is a single ~300KB data module, so it stays OUT of the main
 *  bundle and loads on demand — the same pattern as the code-block language
 *  packs. Two consumers:
 *    - markdown-live: renders a known `:shortcode:` as its glyph. On the
 *      first Emoji node it kicks the load and refreshes decorations when the
 *      data lands.
 *    - EmojiSwitcher (Cmd-E): the picker list.
 *
 *  The vault file always keeps the literal `:shortcode:` text — glyphs are
 *  render-time only, and how a glyph is drawn is the reader's font stack's
 *  business. */

export interface GemojiEntry {
  emoji: string
  names: string[]
  description: string
}

let nameToEmoji: Record<string, string> | null = null
let list: GemojiEntry[] | null = null
let inflight: Promise<void> | null = null

/** Kick (or join) the dataset load. Resolves when the maps are queryable. */
export function loadEmojiData(): Promise<void> {
  inflight ??= import('gemoji').then((m) => {
    nameToEmoji = m.nameToEmoji
    list = m.gemoji
  })
  return inflight
}

/** The name→glyph map, or null while the dataset hasn't loaded yet. */
export function getNameToEmoji(): Record<string, string> | null {
  return nameToEmoji
}

/** The full entry list (for the picker), or null before load. */
export function getGemojiList(): GemojiEntry[] | null {
  return list
}

export interface ShortcodeToken {
  /** Column of the opening `:` within the line. */
  start: number
  /** Column just past the token (past the closing `:` when present). */
  end: number
  /** The inner text, colons stripped — the picker's seed query. */
  query: string
}

// Same charset as the md-emoji parser (GitHub names: letters, digits,
// underscore, hyphen, signs).
const TOKEN_RE = /:[A-Za-z0-9_+-]*:?/g

/** Find the `:shortcode`/`:shortcode:` token the cursor is touching, if any.
 *  `col` is the cursor's column within `lineText`. Touching follows editing
 *  intent (cursor drawn as `|`):
 *    - `|:smile:` and anywhere inside — YES: the cursor sits on the emoji,
 *      Cmd-E means "act on this one".
 *    - `:foo|` (unterminated) — YES: mid-typing, Cmd-E finishes it.
 *    - `:smile:|` (just past a CLOSED token) — NO: the token is done and the
 *      cursor has moved on; Cmd-E means "insert a new one here".
 *  Returns null for a bare/empty `:`. */
export function shortcodeTokenAt(lineText: string, col: number): ShortcodeToken | null {
  TOKEN_RE.lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = TOKEN_RE.exec(lineText))) {
    const start = m.index
    const end = start + m[0].length
    if (start > col) break
    const closed = m[0].length > 1 && m[0].endsWith(':')
    const touches = closed ? col < end : col <= end
    if (col >= start && touches) {
      const query = m[0].slice(1, closed ? -1 : undefined)
      return query ? { start, end, query } : null
    }
  }
  return null
}
