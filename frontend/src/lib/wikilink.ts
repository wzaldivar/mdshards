/*
 * Obsidian-style `[[target]]` and `[[target|alias]]` wiki links.
 *
 * Plugs into @codemirror/lang-markdown via `markdown({ extensions: [Wikilink] })`
 * so the inline parser sees `[[…]]` and emits a `Wikilink` node. `markdown-live`
 * then takes that node and (when the cursor is elsewhere) hides the brackets,
 * collapses the optional `|alias` separator + target, and decorates the visible
 * text as a clickable link.
 *
 * Resolution is deliberately simple: the target string IS the vault doc-id —
 * `[[notes/today]]` navigates to `/notes/today`. No shortest-unique-path magic.
 * Newlines and nested `[[` are rejected so a malformed run doesn't swallow the
 * rest of the paragraph.
 */

import type { InlineParser, MarkdownConfig } from '@lezer/markdown'

const OPEN_BRACKET = 91 // [
const CLOSE_BRACKET = 93 // ]
const PIPE = 124 // |
const NEWLINE = 10

const WikilinkInline: InlineParser = {
  name: 'Wikilink',
  // Run before the standard Link parser so `[[…]]` is captured as a wikilink
  // rather than as a malformed `[link]` opening.
  before: 'Link',
  parse(cx, next, pos) {
    if (next !== OPEN_BRACKET) return -1
    if (cx.char(pos + 1) !== OPEN_BRACKET) return -1

    let scan = pos + 2
    let sawPipe = false
    let pipeAt = -1
    while (scan < cx.end) {
      const c = cx.char(scan)
      if (c === NEWLINE) return -1
      // Reject nested `[[` so `[[ a [[ b ]] ]]` doesn't grab the whole span.
      if (c === OPEN_BRACKET && cx.char(scan + 1) === OPEN_BRACKET) return -1
      if (c === CLOSE_BRACKET && cx.char(scan + 1) === CLOSE_BRACKET) break
      if (c === PIPE && !sawPipe) {
        sawPipe = true
        pipeAt = scan
      }
      scan++
    }
    if (scan >= cx.end) return -1
    const end = scan + 2 // past the closing ]]

    // Reject empty target — `[[]]` and `[[|alias]]` are noise, not a link.
    const targetEnd = sawPipe ? pipeAt : scan
    if (targetEnd - (pos + 2) === 0) return -1

    return cx.addElement(cx.elt('Wikilink', pos, end))
  },
}

export const Wikilink: MarkdownConfig = {
  defineNodes: ['Wikilink'],
  parseInline: [WikilinkInline],
}

export interface WikilinkParts {
  /** The doc-id portion before the optional `|`. */
  target: string
  /** The label after the `|`, or null if there's no pipe. */
  alias: string | null
}

/** Parse the raw inner text of a Wikilink node (everything between `[[` and
 *  `]]`). Returns null if the content is empty. */
export function parseWikilinkBody(inner: string): WikilinkParts | null {
  if (inner === '') return null
  const pipe = inner.indexOf('|')
  if (pipe === -1) return { target: inner, alias: null }
  const target = inner.slice(0, pipe)
  if (target === '') return null
  return { target, alias: inner.slice(pipe + 1) }
}

/** Strip the surrounding `[[`/`]]` and run `parseWikilinkBody`. Returns null if
 *  the input isn't a well-formed wikilink. */
export function parseWikilink(raw: string): WikilinkParts | null {
  if (!raw.startsWith('[[') || !raw.endsWith(']]')) return null
  return parseWikilinkBody(raw.slice(2, -2))
}
