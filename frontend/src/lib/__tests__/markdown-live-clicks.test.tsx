import { afterEach, describe, expect, it, vi } from 'vitest'
import { EditorSelection, EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { markdown } from '@codemirror/lang-markdown'
import { Autolink, Strikethrough, Table, TaskList } from '@lezer/markdown'
import { blockquote, codeblock, hideMarks, htmlBlock, lists } from '@retronav/ixora'
import { markdownLive } from '../markdown-live'
import { Wikilink } from '../wikilink'

/*
 * The mousedown click handler — the ONLY interactive piece of the live
 * preview. Wiki links navigate intra-app via onNavigate; regular links open
 * a new tab (never blowing away the current note), with root-absolute hrefs
 * routed through backendUrl so a sub-path mount's prefix applies.
 */

let view: EditorView | null = null

function mountWith(doc: string, onNavigate: (t: string) => void = () => {}): EditorView {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const state = EditorState.create({
    doc,
    // park the cursor at 0 (the intro line) so decorations render
    selection: EditorSelection.cursor(0),
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

function mousedown(el: Element): void {
  el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }))
}

afterEach(() => {
  view?.destroy()
  view = null
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

describe('live-preview click handling', () => {
  it('clicking a wikilink navigates intra-app with the raw target', () => {
    const onNavigate = vi.fn()
    mountWith('intro\n\ngo to [[notes/target|somewhere]]\n', onNavigate)
    const wiki = document.querySelector('.cm-md-wikilink')!
    mousedown(wiki)
    expect(onNavigate).toHaveBeenCalledWith('notes/target')
  })

  it('clicking a bare #section wikilink reports the anchor target verbatim', () => {
    const onNavigate = vi.fn()
    mountWith('intro\n\njump to [[#Section Foo]]\n', onNavigate)
    const wiki = document.querySelector('.cm-md-wikilink')!
    expect(wiki.textContent).toBe('#Section Foo')
    mousedown(wiki)
    // The full anchor (page + #section) is handed to onNavigate; the Editor
    // splits it into page/section and decides scroll-vs-navigate.
    expect(onNavigate).toHaveBeenCalledWith('#Section Foo')
  })

  it('clicking a cross-note note#section wikilink reports the full target', () => {
    const onNavigate = vi.fn()
    mountWith('intro\n\nsee [[notes/other#Deep|there]]\n', onNavigate)
    const wiki = document.querySelector('.cm-md-wikilink')!
    expect(wiki.textContent).toBe('there')
    mousedown(wiki)
    expect(onNavigate).toHaveBeenCalledWith('notes/other#Deep')
  })

  it('clicking an external link opens a new tab with noopener', () => {
    const open = vi.fn()
    vi.stubGlobal('open', open)
    mountWith('intro\n\n[docs](https://example.com/docs)\n')
    const link = document.querySelector('.cm-md-link')!
    mousedown(link)
    expect(open).toHaveBeenCalledWith(
      'https://example.com/docs',
      '_blank',
      'noopener,noreferrer',
    )
  })

  it('routes root-absolute link hrefs through backendUrl (sub-path prefix)', () => {
    const open = vi.fn()
    vi.stubGlobal('open', open)
    const meta = document.createElement('meta')
    meta.setAttribute('name', 'mdshards-home-path')
    meta.setAttribute('content', '/wiki')
    document.head.appendChild(meta)
    try {
      mountWith('intro\n\n[report](/reports/q3.pdf)\n')
      mousedown(document.querySelector('.cm-md-link')!)
      expect(open).toHaveBeenCalledWith('/wiki/reports/q3.pdf', '_blank', 'noopener,noreferrer')
    } finally {
      meta.remove()
    }
  })

  it('leaves relative link hrefs to browser resolution (note-relative URLs)', () => {
    const open = vi.fn()
    vi.stubGlobal('open', open)
    mountWith('intro\n\n[sib](sibling.pdf)\n')
    mousedown(document.querySelector('.cm-md-link')!)
    expect(open).toHaveBeenCalledWith('sibling.pdf', '_blank', 'noopener,noreferrer')
  })

  it('ignores clicks on plain text', () => {
    const onNavigate = vi.fn()
    const open = vi.fn()
    vi.stubGlobal('open', open)
    mountWith('intro\n\njust words here\n', onNavigate)
    const line = [...document.querySelectorAll('.cm-line')].at(-1)!
    mousedown(line)
    expect(onNavigate).not.toHaveBeenCalled()
    expect(open).not.toHaveBeenCalled()
  })

  it('renders a labeled placeholder for a vault-escaping image ref', () => {
    // ../../pic.png from notes/today escapes the vault → empty src → the
    // widget renders a role="img" span instead of a broken <img>.
    mountWith('intro\n\n![escapee](../../pic.png)\n')
    const missing = document.querySelector('.cm-md-image-missing')!
    expect(missing).not.toBeNull()
    expect(missing.getAttribute('role')).toBe('img')
    expect(missing.getAttribute('aria-label')).toBe('escapee')
    // no real image element for the blocked ref (CM may render unrelated imgs)
    expect(document.querySelectorAll('img.cm-md-image')).toHaveLength(0)
  })
})
