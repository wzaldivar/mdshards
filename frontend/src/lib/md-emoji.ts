import { tags } from '@lezer/highlight'
import type { MarkdownConfig } from '@lezer/markdown'

/** `:shortcode:` parser. `@lezer/markdown` ships an `Emoji` extension but its
 *  charset is `[a-zA-Z_0-9]` only — GitHub's actual shortcode vocabulary
 *  (the gemoji dataset we resolve against) also uses hyphens and signs:
 *  `:t-rex:` 🦖, `:e-mail:`, `:+1:`, `:-1:`. This is the same parser with the
 *  charset widened to match gemoji's names. Resolution to a glyph (or not —
 *  unknown codes stay raw text) happens later in markdown-live. */
export const EmojiShortcode: MarkdownConfig = {
  defineNodes: [{ name: 'Emoji', style: tags.character }],
  parseInline: [
    {
      name: 'Emoji',
      parse(cx, next, pos) {
        if (next !== 58 /* ':' */) return -1
        const match = /^[a-zA-Z_0-9+-]+:/.exec(cx.slice(pos + 1, cx.end))
        if (!match) return -1
        return cx.addElement(cx.elt('Emoji', pos, pos + 1 + match[0].length))
      },
    },
  ],
}
