import { afterEach, describe, expect, it } from 'vitest'
import { EditorSelection, EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { markdown } from '@codemirror/lang-markdown'
import { syntaxHighlighting } from '@codemirror/language'
import { Autolink, Strikethrough, Subscript, Superscript, Table, TaskList } from '@lezer/markdown'
import { blockquote, codeblock, hideMarks, htmlBlock, lists } from '@retronav/ixora'
import { markdownLive } from '../markdown-live'
import { catppuccinHighlight } from '../cm-highlight'
import { Highlight } from '../md-highlight'
import { Wikilink } from '../wikilink'

/*
 * Regression: inline formatting inside a list item must keep its own emphasis
 * styling. lezer-markdown scopes `tags.list` over the WHOLE list subtree, so a
 * `t.list` color rule in the highlight style tints every list item's content
 * AND, as an equal-specificity single-class selector, overrides the nested
 * bold/italic/strike colors in the cascade — flattening `**bold**`, `*em*`,
 * `~~strike~~` and `` `code` `` inside lists. We dropped the `t.list` rule so
 * list content renders as plain prose; this guards it staying gone.
 */

let view: EditorView | null = null

function mount(doc: string): EditorView {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const state = EditorState.create({
    doc,
    // Cursor at EOF so no list line is "touched" (which would reveal raw markup).
    selection: EditorSelection.cursor(doc.length),
    extensions: [
      markdown({
        extensions: [Table, TaskList, Strikethrough, Subscript, Superscript, Highlight, Autolink, Wikilink],
      }),
      syntaxHighlighting(catppuccinHighlight, { fallback: true }),
      hideMarks(),
      lists(),
      blockquote(),
      codeblock(),
      htmlBlock,
      markdownLive({ noteDocId: 'notes/today', onNavigate: () => {} }),
    ],
  })
  view = new EditorView({ state, parent: host })
  return view
}

/** Highlight-style class names the current stylesheet assigns to the given
 *  CSS custom property (e.g. `--italic-color`). Returns the set so a test can
 *  assert a rendered span carries the right emphasis class. */
function classesFor(cssVar: string): Set<string> {
  const rules = (
    catppuccinHighlight as unknown as { module: { getRules(): string } }
  ).module
    .getRules()
    .split('\n')
  const out = new Set<string>()
  for (const rule of rules) {
    const m = /^\.(\S+)\s*\{([^}]*)\}/.exec(rule)
    if (m && m[2].includes(cssVar)) out.add(m[1])
  }
  return out
}

/** The rendered <span> whose text (after mark-hiding) equals `text`. */
function spanFor(text: string): HTMLElement | undefined {
  return [...document.querySelectorAll<HTMLElement>('.cm-line span')].find(
    (s) => s.textContent === text,
  )
}

afterEach(() => {
  view?.destroy()
  view = null
  document.body.innerHTML = ''
})

describe('inline formatting inside list items', () => {
  it('bold in a list carries the strong color, not a flat list tint', () => {
    mount('- this should be **bold**\n')
    const span = spanFor('bold')
    expect(span).toBeTruthy()
    const boldClasses = classesFor('--bold-color')
    expect([...span!.classList].some((c) => boldClasses.has(c))).toBe(true)
    // And it must NOT also carry the list-marker color that used to win.
    const listClasses = classesFor('--list-marker-color')
    expect([...span!.classList].some((c) => listClasses.has(c))).toBe(false)
  })

  it('italic in a task item keeps the emphasis color', () => {
    mount('- [ ] my *very important* task\n')
    const span = spanFor('very important')
    expect(span).toBeTruthy()
    const italicClasses = classesFor('--italic-color')
    expect([...span!.classList].some((c) => italicClasses.has(c))).toBe(true)
  })

  it('strikethrough in a list keeps the strike color', () => {
    mount('- ~~gone~~ item\n')
    const span = spanFor('gone')
    expect(span).toBeTruthy()
    const strikeClasses = classesFor('--strike-color')
    expect([...span!.classList].some((c) => strikeClasses.has(c))).toBe(true)
  })

  it('plain list text is unstyled prose (no highlight class)', () => {
    mount('- just some plain text\n')
    // The list content text node should not be wrapped in a highlight span.
    const plain = spanFor(' just some plain text')
    expect(plain).toBeUndefined()
  })
})
