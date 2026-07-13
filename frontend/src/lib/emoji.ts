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
