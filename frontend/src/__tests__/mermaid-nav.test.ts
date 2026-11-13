import { afterEach, describe, expect, it, vi } from 'vitest'
import { markdown } from '@codemirror/lang-markdown'
import { ensureSyntaxTree } from '@codemirror/language'
import { EditorSelection, EditorState, type SelectionRange } from '@codemirror/state'
import { EditorView, runScopeHandlers } from '@codemirror/view'
import { getCM, vim } from '@replit/codemirror-vim'
import { mermaidDiagrams } from '../lib/mermaid'

// The diagram itself is irrelevant here (and mermaid can't lay out in jsdom);
// what matters is that a closed fence becomes one block widget.
vi.mock('mermaid', () => ({
  default: {
    initialize: () => {},
    render: async () => ({ svg: '<svg></svg>' }),
  },
}))

// Lines (0-based): 0 `above`, 1-4 the fence, 5 `below`, 6 `last`.
const DOC = ['above', '```mermaid', 'graph TD', 'A-->B', '```', 'below', 'last'].join('\n')
const FENCE_FROM = DOC.indexOf('```mermaid')
const FENCE_TO = DOC.indexOf('\nbelow')

let view: EditorView | null = null

/** jsdom has no layout, so CodeMirror can't move vertically by itself. Stand
 *  in for it the way a real browser behaves around a block widget: one step
 *  moves a logical line, and a rendered diagram is skipped in a single step. */
function fakeMoveVertically(v: EditorView) {
  return (start: SelectionRange, forward: boolean): SelectionRange => {
    const doc = v.state.doc
    let n = doc.lineAt(start.head).number + (forward ? 1 : -1)
    while (n >= 1 && n <= doc.lines) {
      const line = doc.line(n)
      if (line.from < FENCE_FROM || line.from > FENCE_TO) return EditorSelection.cursor(line.from)
      n += forward ? 1 : -1
    }
    return EditorSelection.cursor(forward ? doc.length : 0)
  }
}

function mount(opts: { doc?: string; cursor?: number; withVim?: boolean } = {}): EditorView {
  const doc = opts.doc ?? DOC
  const state = EditorState.create({
    doc,
    selection: { anchor: opts.cursor ?? 0 },
    extensions: [opts.withVim ? vim() : [], markdown(), mermaidDiagrams()],
  })
  const parent = document.createElement('div')
  document.body.appendChild(parent)
  view = new EditorView({ state, parent })
  // The field rebuilds when the parser has covered more of the doc; force a
  // full parse and nudge it so the fence is decorated before the test acts.
  ensureSyntaxTree(view.state, doc.length, 5000)
  view.dispatch({ selection: view.state.selection })
  vi.spyOn(view, 'moveVertically').mockImplementation(fakeMoveVertically(view))
  return view
}

function press(v: EditorView, key: 'ArrowDown' | 'ArrowUp'): boolean {
  return runScopeHandlers(v, new KeyboardEvent('keydown', { key }), 'editor')
}

afterEach(() => {
  view?.dom.parentElement?.remove()
  view?.destroy()
  view = null
})

describe('arrowing into a mermaid diagram', () => {
  it('renders a closed fence as one block widget', () => {
    const v = mount()
    expect(v.dom.querySelectorAll('.cm-md-mermaid')).toHaveLength(1)
  })

  it('ArrowDown stops on the opening fence instead of jumping over it', () => {
    const v = mount({ cursor: 0 })
    expect(press(v, 'ArrowDown')).toBe(true)
    expect(v.state.selection.main.head).toBe(FENCE_FROM)
    // The selection now touches the fence, so the source is revealed.
    expect(v.dom.querySelectorAll('.cm-md-mermaid')).toHaveLength(0)
  })

  it('ArrowUp stops on the closing fence', () => {
    const v = mount({ cursor: DOC.indexOf('below') })
    expect(press(v, 'ArrowUp')).toBe(true)
    expect(v.state.selection.main.head).toBe(FENCE_TO)
  })

  it('leaves a move that crosses no diagram to the default motion', () => {
    const v = mount({ cursor: DOC.indexOf('below') })
    press(v, 'ArrowDown')
    expect(v.state.selection.main.head).toBe(DOC.indexOf('below'))
  })

  it('leaves a non-empty selection alone', () => {
    const v = mount()
    v.dispatch({ selection: { anchor: 0, head: 3 } })
    press(v, 'ArrowDown')
    expect(v.state.selection.main.head).toBe(3)
  })
})

describe("vim's counted line motions around a mermaid diagram", () => {
  function cmOf(v: EditorView) {
    const cm = getCM(v)
    if (!cm) throw new Error('vim adapter missing')
    return cm
  }

  it("counts the diagram's source lines going down", () => {
    const cm = cmOf(mount({ withVim: true }))
    expect(cm.findPosV({ line: 0, ch: 0 }, 1, 'line').line).toBe(1)
    expect(cm.findPosV({ line: 0, ch: 0 }, 3, 'line').line).toBe(3)
    // Six steps from `above`: four fence lines, then `below`, then `last`.
    expect(cm.findPosV({ line: 0, ch: 0 }, 6, 'line').line).toBe(6)
  })

  it("counts the diagram's source lines going up", () => {
    const cm = cmOf(mount({ withVim: true, cursor: DOC.length }))
    expect(cm.findPosV({ line: 5, ch: 0 }, -1, 'line').line).toBe(4)
    expect(cm.findPosV({ line: 5, ch: 0 }, -5, 'line').line).toBe(0)
  })

  it('clamps the column to the length of the line it lands on', () => {
    const cm = cmOf(mount({ withVim: true }))
    // `above` is 5 long, the closing fence 3.
    expect(cm.findPosV({ line: 5, ch: 5 }, -1, 'line')).toEqual({ line: 4, ch: 3 })
  })

  it('hands a step past either end of the document to the stock motion', () => {
    const cm = cmOf(mount({ withVim: true }))
    expect(cm.findPosV({ line: 0, ch: 0 }, -1, 'line').line).toBe(0)
    expect(cm.findPosV({ line: 6, ch: 0 }, 1, 'line').line).toBe(6)
  })

  it('keeps the stock motion for non-line units', () => {
    const v = mount({ withVim: true })
    const moves = vi.mocked(v.moveVertically)
    moves.mockClear()
    cmOf(v).findPosV({ line: 0, ch: 0 }, 1, 'page')
    // One stock call, not one per source line.
    expect(moves).toHaveBeenCalledTimes(1)
  })

  it('keeps the stock motion in a note without diagrams', () => {
    const cm = cmOf(mount({ withVim: true, doc: 'one\ntwo\nthree' }))
    expect(cm.findPosV({ line: 0, ch: 0 }, 2, 'line').line).toBe(2)
  })
})
