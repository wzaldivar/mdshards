import { tags } from '@lezer/highlight'
import type { DelimiterType, MarkdownConfig } from '@lezer/markdown'

/** `==highlighted==` — markdownguide's extended-syntax highlight. Not shipped
 *  by `@lezer/markdown`, so this mirrors its own Strikethrough extension
 *  (`~~` → `==`, exactly two markers, same flanking rules): a delimiter-based
 *  inline parser producing `Highlight` wrapping two `HighlightMark`s.
 *  Rendering: markdown-live tags the span with `.cm-md-mark` (style.css) and
 *  hides the marks cursor-aware like the other inline markup. */

// Same punctuation classification lezer-markdown uses for flanking checks,
// including the unicode-property upgrade where the engine supports it.
let Punctuation = /[!-/:-@[-`{-~\xA1‐-‧]/
try {
  Punctuation = new RegExp('[\\p{Pc}|\\p{Pd}|\\p{Pe}|\\p{Pf}|\\p{Pi}|\\p{Po}|\\p{Ps}]', 'u')
} catch {
  /* older engines keep the ASCII approximation */
}

const HighlightDelim: DelimiterType = { resolve: 'Highlight', mark: 'HighlightMark' }

export const Highlight: MarkdownConfig = {
  defineNodes: [
    { name: 'Highlight', style: { 'Highlight/...': tags.special(tags.content) } },
    { name: 'HighlightMark', style: tags.processingInstruction },
  ],
  parseInline: [
    {
      name: 'Highlight',
      parse(cx, next, pos) {
        // Exactly two `=`: reject a lone one and runs of three or more (a
        // `===` is far more likely a setext underline or literal text). The
        // pos-1 check stops the parser from re-matching the tail pair of a
        // longer run (`===b===` would otherwise match its inner `==b==`).
        if (
          next !== 61 /* '=' */ ||
          cx.char(pos + 1) !== 61 ||
          cx.char(pos + 2) === 61 ||
          cx.char(pos - 1) === 61
        )
          return -1
        const before = cx.slice(pos - 1, pos)
        const after = cx.slice(pos + 2, pos + 3)
        const sBefore = /\s|^$/.test(before)
        const sAfter = /\s|^$/.test(after)
        const pBefore = Punctuation.test(before)
        const pAfter = Punctuation.test(after)
        return cx.addDelimiter(
          HighlightDelim,
          pos,
          pos + 2,
          !sAfter && (!pAfter || sBefore || pBefore),
          !sBefore && (!pBefore || sAfter || pAfter),
        )
      },
      after: 'Emphasis',
    },
  ],
}
