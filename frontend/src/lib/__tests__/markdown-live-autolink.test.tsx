import { afterEach, describe, expect, it, vi } from 'vitest'
import { EditorSelection, EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { markdown } from '@codemirror/lang-markdown'
import { Autolink, Strikethrough, Table, TaskList } from '@lezer/markdown'
import { blockquote, codeblock, hideMarks, htmlBlock, lists } from '@retronav/ixora'
import { markdownLive } from '../markdown-live'
import { Wikilink } from '../wikilink'

/*
 * Bare http(s):// URLs and emails render as clickable inline links, plus the
 * angle-bracket autolink form. A URL that is really a link/image/reference
 * target must NOT be double-linkified, and a cursor on the URL leaves it raw
 * (editable) per the touch convention.
 */

let view: EditorView | null = null

function mountWith(doc: string, cursor = 0, onNavigate: (t: string) => void = () => {}): EditorView {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const state = EditorState.create({
    doc,
    selection: EditorSelection.cursor(cursor),
    extensions: [
      markdown({ extensions: [Table, TaskList, Strikethrough, Autolink, Wikilink] }),
      hideMarks(),
      lists(),
      blockquote(),
      codeblock(),
      htmlBlock,
      markdownLive({ noteDocId: 'notes/today', onNavigate }),
    ],
  })
  view = new EditorView({ state, parent: host })
  return view
}

function links(): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>('.cm-md-link')]
}

function mousedown(el: Element): void {
  el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }))
}

afterEach(() => {
  view?.destroy()
  view = null
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

describe('autolinking bare URLs and emails', () => {
  it('linkifies a bare https:// URL and opens it in a new tab on click', () => {
    const open = vi.fn()
    vi.stubGlobal('open', open)
    mountWith('intro\n\nsee https://example.com/docs for more\n')
    const link = links().find((l) => l.dataset.href === 'https://example.com/docs')
    expect(link).toBeTruthy()
    expect(link!.textContent).toBe('https://example.com/docs')
    mousedown(link!)
    expect(open).toHaveBeenCalledWith(
      'https://example.com/docs',
      '_blank',
      'noopener,noreferrer',
    )
  })

  it('linkifies http:// too', () => {
    mountWith('intro\n\nhttp://plain.example is fine\n')
    expect(links().some((l) => l.dataset.href === 'http://plain.example')).toBe(true)
  })

  it('linkifies a bare email with a mailto: href', () => {
    mountWith('intro\n\nmail me at a.b+c@sub.example.com today\n')
    const link = links().find((l) => l.dataset.href === 'mailto:a.b+c@sub.example.com')
    expect(link).toBeTruthy()
    expect(link!.textContent).toBe('a.b+c@sub.example.com')
  })

  it('linkifies a www. host with an https:// href', () => {
    mountWith('intro\n\nvisit www.example.com now\n')
    expect(links().some((l) => l.dataset.href === 'https://www.example.com')).toBe(true)
  })

  it('renders an angle autolink clickable with the < > hidden', () => {
    mountWith('intro\n\ncontact <https://angle.example> here\n')
    const link = links().find((l) => l.dataset.href === 'https://angle.example')
    expect(link).toBeTruthy()
    // the rendered link text is just the URL — no surrounding brackets
    expect(link!.textContent).toBe('https://angle.example')
  })

  it('does NOT double-linkify the url of a [label](url) link', () => {
    mountWith('intro\n\n[docs](https://example.com/x)\n')
    // exactly one link, and it is the label — not the url
    expect(links()).toHaveLength(1)
    expect(links()[0].dataset.href).toBe('https://example.com/x')
    expect(links()[0].textContent).toBe('docs')
  })

  it('does NOT linkify a reference definition target', () => {
    mountWith('intro\n\n[ref]: https://example.com/def\n')
    expect(links().some((l) => l.dataset.href === 'https://example.com/def')).toBe(false)
  })

  it('leaves the URL raw (no link) when the cursor is on it — editable', () => {
    const doc = 'intro\n\nsee https://example.com/docs here\n'
    // place the cursor inside the URL
    mountWith(doc, doc.indexOf('https://') + 5)
    expect(links()).toHaveLength(0)
  })

  it('does not autolink inside an inline-code span', () => {
    mountWith('intro\n\nliteral `https://nope.example` stays raw\n')
    expect(links()).toHaveLength(0)
  })
})
