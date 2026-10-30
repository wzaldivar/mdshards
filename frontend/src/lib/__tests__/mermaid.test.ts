import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { EditorSelection, EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { markdown } from '@codemirror/lang-markdown'
import { codeblock } from '@retronav/ixora'
import { mermaidDiagrams } from '../mermaid'

/*
 * ` ```mermaid ` fence → diagram widget. mermaid itself needs real layout
 * (jsdom has none), so it's mocked: these tests pin the cursor rule, the
 * which-fences-qualify rule, error display, and SVG sanitization — the
 * parts we own.
 */

const { initialize, render } = vi.hoisted(() => ({
  initialize: vi.fn(),
  render: vi.fn(async (_id: string, src: string) => {
    if (src.includes('BROKEN')) throw new Error('Parse error on line 1')
    if (src.includes('EVIL')) {
      return {
        svg: '<svg><script>alert(1)</script><g onload="alert(2)"><text>evil</text></g></svg>',
      }
    }
    return { svg: `<svg data-src="${src.length}"><text>ok</text></svg>` }
  }),
}))
vi.mock('mermaid', () => ({ default: { initialize, render } }))

// jsdom loads no stylesheet; stand in for the Catppuccin palette the widget
// themes from (an empty token makes it wait for the CSS to land).
beforeAll(() => {
  document.documentElement.style.setProperty('--ctp-base', '239, 241, 245')
})

let view: EditorView | null = null

function mount(doc: string, selection = 0): EditorView {
  const host = document.createElement('div')
  document.body.appendChild(host)
  view = new EditorView({
    state: EditorState.create({
      doc,
      selection: EditorSelection.cursor(selection),
      extensions: [markdown(), codeblock(), mermaidDiagrams()],
    }),
    parent: host,
  })
  return view
}

/** Wait for the async render to land in the widget. */
async function settle(): Promise<void> {
  for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0))
}

afterEach(() => {
  view?.dom.parentElement?.remove()
  view?.destroy()
  view = null
})

const FLOW = 'graph TD\n  A --> B'
const NOTE = `intro\n\n\`\`\`mermaid\n${FLOW}\n\`\`\`\n\noutro`

describe('mermaid fences', () => {
  it('renders a diagram while the cursor is elsewhere', async () => {
    const v = mount(NOTE, 0)
    await settle()
    const el = v.dom.querySelector('.cm-md-mermaid')
    expect(el).not.toBeNull()
    expect(el!.querySelector('svg')).not.toBeNull()
    expect(v.dom.textContent).not.toContain('A --> B')
    expect(render).toHaveBeenCalledWith(expect.any(String), FLOW)
  })

  it('shows the raw source while the cursor is inside the fence', () => {
    const v = mount(NOTE, NOTE.indexOf('A -->'))
    expect(v.dom.querySelector('.cm-md-mermaid')).toBeNull()
    expect(v.dom.textContent).toContain('A --> B')
  })

  it('reveals the source when the cursor reaches the fence boundary', () => {
    const v = mount(NOTE, 0)
    expect(v.dom.querySelector('.cm-md-mermaid')).not.toBeNull()
    v.dispatch({ selection: { anchor: NOTE.indexOf('```') } })
    expect(v.dom.querySelector('.cm-md-mermaid')).toBeNull()
  })

  it('leaves other languages and unclosed fences alone', () => {
    const v = mount('x\n\n```js\nlet a\n```\n\n```mermaid\ngraph TD\n  A --> B', 0)
    expect(v.dom.querySelector('.cm-md-mermaid')).toBeNull()
    expect(v.dom.textContent).toContain('let a')
    expect(v.dom.textContent).toContain('A --> B')
  })

  it('shows the parse error instead of a blank block', async () => {
    const v = mount('x\n\n```mermaid\nBROKEN\n```', 0)
    await settle()
    const el = v.dom.querySelector('.cm-md-mermaid')
    expect(el?.classList.contains('cm-md-mermaid-error')).toBe(true)
    expect(el?.textContent).toContain('Parse error on line 1')
  })

  it('shows an error rather than hanging when mermaid itself throws', async () => {
    // Regression: a throw from initialize() (WebKit, cold load, empty theme
    // tokens) used to escape the try and leave "Rendering diagram…" forever.
    initialize.mockImplementationOnce(() => {
      throw new Error('Unsupported color format: ""')
    })
    // Flip the scheme so initialize() actually runs for this render.
    // jsdom has no matchMedia, so the earlier tests rendered "light".
    vi.stubGlobal('matchMedia', () => ({
      matches: true,
      addEventListener: () => {},
      removeEventListener: () => {},
    }))
    const v = mount('x\n\n```mermaid\ngraph LR\n  Init --> Throws\n```', 0)
    await settle()
    const el = v.dom.querySelector('.cm-md-mermaid')
    expect(el?.classList.contains('cm-md-mermaid-pending')).toBe(false)
    expect(el?.textContent).toContain('Unsupported color format')
    vi.unstubAllGlobals()
  })

  it('sanitizes the rendered SVG', async () => {
    const v = mount('x\n\n```mermaid\nEVIL\n```', 0)
    await settle()
    const el = v.dom.querySelector('.cm-md-mermaid')!
    expect(el.querySelector('svg')).not.toBeNull()
    expect(el.innerHTML).not.toContain('<script')
    expect(el.innerHTML).not.toContain('onload')
  })

  it('does not change the document', async () => {
    const v = mount(NOTE, 0)
    await settle()
    expect(v.state.doc.toString()).toBe(NOTE)
  })
})
