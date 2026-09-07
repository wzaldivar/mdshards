import { afterEach, describe, expect, it } from 'vitest'
import { EditorSelection, EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { markdown } from '@codemirror/lang-markdown'
import { findHeadingPos, scrollToHeading } from '../heading-nav'
import { parseWikilinkTarget } from '../wikilink'

/*
 * Section-anchor navigation: `[[#Heading]]` / `[[note#Heading]]`. These cover
 * the pure target split and the heading resolver (all six ATX levels + Setext,
 * case/whitespace-insensitive matching). The click→scroll wiring and the
 * cross-note load-then-scroll are exercised end-to-end in the e2e suite.
 */

function stateOf(doc: string): EditorState {
  return EditorState.create({ doc, extensions: [markdown()] })
}

describe('parseWikilinkTarget', () => {
  it('splits a note#section target', () => {
    expect(parseWikilinkTarget('notes/x#Foo Bar')).toEqual({ page: 'notes/x', section: 'Foo Bar' })
  })
  it('treats a bare #section as the current note', () => {
    expect(parseWikilinkTarget('#Foo')).toEqual({ page: '', section: 'Foo' })
  })
  it('leaves a plain note target without a section', () => {
    expect(parseWikilinkTarget('notes/x')).toEqual({ page: 'notes/x', section: null })
  })
  it('splits on the first # only', () => {
    expect(parseWikilinkTarget('a#b#c')).toEqual({ page: 'a', section: 'b#c' })
  })
})

describe('findHeadingPos', () => {
  const doc = [
    'intro',
    '',
    '# Heading One',
    '',
    'body',
    '',
    '## Heading Two',
    '',
    '### Heading Three',
    '',
    '#### Heading Four',
    '',
    '##### Heading Five',
    '',
    '###### Heading Six',
    '',
    'Setext Heading',
    '===',
    '',
  ].join('\n')

  it.each([
    ['Heading One', '# Heading One'],
    ['Heading Two', '## Heading Two'],
    ['Heading Three', '### Heading Three'],
    ['Heading Four', '#### Heading Four'],
    ['Heading Five', '##### Heading Five'],
    ['Heading Six', '###### Heading Six'],
  ])('resolves ATX heading %s (all six levels)', (section, lineText) => {
    const state = stateOf(doc)
    const pos = findHeadingPos(state, section)
    expect(pos).not.toBeNull()
    expect(state.doc.lineAt(pos!).text).toBe(lineText)
  })

  it('resolves a Setext heading to its text line', () => {
    const state = stateOf(doc)
    const pos = findHeadingPos(state, 'Setext Heading')
    expect(pos).not.toBeNull()
    expect(state.doc.lineAt(pos!).text).toBe('Setext Heading')
  })

  it('matches case- and whitespace-insensitively', () => {
    const state = stateOf(doc)
    expect(findHeadingPos(state, '  heading   three ')).toBe(findHeadingPos(state, 'Heading Three'))
  })

  it('returns null for an unknown or empty section', () => {
    const state = stateOf(doc)
    expect(findHeadingPos(state, 'Nope')).toBeNull()
    expect(findHeadingPos(state, '   ')).toBeNull()
  })
})

describe('scrollToHeading', () => {
  let view: EditorView | null = null
  afterEach(() => {
    view?.destroy()
    view = null
    document.body.innerHTML = ''
  })

  it('moves the cursor to the matched heading and reports success', () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const doc = 'top\n\n# Alpha\n\nmid\n\n## Beta\n'
    view = new EditorView({
      state: EditorState.create({
        doc,
        selection: EditorSelection.cursor(0),
        extensions: [markdown()],
      }),
      parent: host,
    })
    expect(scrollToHeading(view, 'Beta')).toBe(true)
    const line = view.state.doc.lineAt(view.state.selection.main.head)
    expect(line.text).toBe('## Beta')
  })

  it('leaves the selection put and returns false when the heading is missing', () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    view = new EditorView({
      state: EditorState.create({
        doc: 'top\n\n# Alpha\n',
        selection: EditorSelection.cursor(0),
        extensions: [markdown()],
      }),
      parent: host,
    })
    expect(scrollToHeading(view, 'Ghost')).toBe(false)
    expect(view.state.selection.main.head).toBe(0)
  })
})
