/*
 * Section navigation for Obsidian-style heading anchors — `[[#Heading]]` (a
 * heading in the current note) and `[[note#Heading]]` (a heading in another
 * note). Resolves a section name to a document offset by matching heading text,
 * then scrolls the editor there.
 *
 * Matches all six ATX levels (`#`…`######`) and both Setext levels
 * (`Heading\n===` / `Heading\n---`). Matching is forgiving the way Obsidian's
 * is: case-insensitive, trimmed, with internal whitespace runs collapsed — the
 * `#`/underline markup never participates.
 */

import { ensureSyntaxTree, syntaxTree } from '@codemirror/language'
import type { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'

const ATX_NAME_RE = /^ATXHeading[1-6]$/
const SETEXT_NAME_RE = /^SetextHeading[12]$/

/** Normalize a heading name / section anchor for comparison. */
function normalize(text: string): string {
  return text.trim().replace(/\s+/g, ' ').toLowerCase()
}

/** The display text of a heading node with its markup stripped: the leading
 *  `#`s (and one optional trailing run of `#`s) for ATX, or the text line above
 *  the `===`/`---` underline for Setext. */
function headingText(state: EditorState, from: number, to: number, name: string): string {
  const raw = state.doc.sliceString(from, to)
  if (ATX_NAME_RE.test(name)) {
    return raw.replace(/^#{1,6}[ \t]*/, '').replace(/[ \t]*#*[ \t]*$/, '')
  }
  // Setext: the node spans the text line plus its underline; the anchor targets
  // the text line.
  const nl = raw.indexOf('\n')
  return nl === -1 ? raw : raw.slice(0, nl)
}

/** Document offset of the first heading whose text matches `section`, or null
 *  if none does. Empty/blank sections never match.
 *
 *  Forces the parse to the end of the document first: the language parse is
 *  time-budgeted, so a plain `syntaxTree(state)` may be truncated before a
 *  heading far down a long note (or, in a bare test state, before the later
 *  headings) — which would make the jump silently miss. `ensureSyntaxTree`
 *  parses through `doc.length`; if it can't within the budget we fall back to
 *  the partial tree rather than not searching at all. */
export function findHeadingPos(state: EditorState, section: string): number | null {
  const wanted = normalize(section)
  if (wanted === '') return null
  let found: number | null = null
  const tree = ensureSyntaxTree(state, state.doc.length, 5_000) ?? syntaxTree(state)
  tree.iterate({
    enter: (node) => {
      if (found !== null) return false
      const isHeading = ATX_NAME_RE.test(node.name) || SETEXT_NAME_RE.test(node.name)
      if (!isHeading) return undefined
      if (normalize(headingText(state, node.from, node.to, node.name)) === wanted) {
        found = node.from
        return false
      }
      return undefined
    },
  })
  return found
}

/** Scroll `view` to the heading matching `section` and place the cursor at its
 *  start (revealing the heading's raw markup, per the touch convention — you're
 *  taken there to read/edit). Returns true if a matching heading was found. */
export function scrollToHeading(view: EditorView, section: string): boolean {
  const pos = findHeadingPos(view.state, section)
  if (pos === null) return false
  const line = view.state.doc.lineAt(pos)
  view.dispatch({
    selection: { anchor: line.from },
    effects: EditorView.scrollIntoView(line.from, { y: 'start', yMargin: 16 }),
  })
  view.focus()
  return true
}
