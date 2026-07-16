import { afterEach, describe, expect, it } from 'vitest'
import { EditorSelection, EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { markdown } from '@codemirror/lang-markdown'
import { Autolink, Strikethrough, Table, TaskList } from '@lezer/markdown'
import { blockquote, codeblock, hideMarks, htmlBlock, lists } from '@retronav/ixora'
import { markdownLive } from '../markdown-live'
import { Wikilink } from '../wikilink'

/*
 * Image widget rendering — the two Obsidian-vault authoring shapes that
 * used to fail:
 *   - `![](pic.png)` with EMPTY alt text (the decoration demanded alt
 *     characters and silently left the run as raw text);
 *   - `![[pic.png]]` / `![[pic.png|label]]` wikilink image embeds
 *     (Obsidian's default embed syntax; target resolves vault-rooted,
 *     exactly like wikilink navigation).
 */

let view: EditorView | null = null

function mountWith(doc: string, selection?: number): EditorView {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const state = EditorState.create({
    doc,
    selection: selection !== undefined ? EditorSelection.cursor(selection) : undefined,
    extensions: [
      markdown({ extensions: [Table, TaskList, Strikethrough, Autolink, Wikilink] }),
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

afterEach(() => {
  view?.destroy()
  view = null
  document.body.innerHTML = ''
})

function imgs(): HTMLImageElement[] {
  return [...document.querySelectorAll('img.cm-md-image')] as HTMLImageElement[]
}

describe('markdown images with empty alt', () => {
  it('renders `![](pic.png)` as an image widget (regression)', () => {
    const doc = 'intro\n\n![](pic.png)\n'
    mountWith(doc, 0)
    expect(imgs()).toHaveLength(1)
    expect(imgs()[0].getAttribute('src')).toBe('/notes/pic.png')
    expect(imgs()[0].getAttribute('alt')).toBe('')
  })

  it('renders an empty-alt image INLINE after text', () => {
    const doc = 'intro\n\nsee here ![](pic.png) mid-sentence\n'
    mountWith(doc, 0)
    expect(imgs()).toHaveLength(1)
  })
})

describe('wikilink image embeds', () => {
  it('renders `![[attachments/pic.png]]` via the server-side embed resolver', () => {
    const doc = 'intro\n\n![[attachments/pic.png]]\n'
    mountWith(doc, 0)
    expect(imgs()).toHaveLength(1)
    // ONE request; /_mdshards/api/embed resolves adjacent-first-else-root server-side
    expect(imgs()[0].getAttribute('src')).toBe(
      '/_mdshards/api/embed?note=notes%2Ftoday&target=attachments%2Fpic.png',
    )
    // the raw markup (bang and brackets) is fully hidden
    expect(document.querySelector('.cm-content')!.textContent).not.toContain('![[')
  })

  it('uses the alias as alt text and encodes spaces in the query', () => {
    const doc = 'intro\n\n![[my pics/my pic.png|the alt]]\n'
    mountWith(doc, 0)
    expect(imgs()).toHaveLength(1)
    expect(imgs()[0].getAttribute('src')).toBe(
      '/_mdshards/api/embed?note=notes%2Ftoday&target=my%20pics%2Fmy%20pic.png',
    )
    expect(imgs()[0].getAttribute('alt')).toBe('the alt')
  })

  it('non-image targets stay raw (transclusion is out of scope)', () => {
    // The stock Image parser owns `![[...]]`, so there is no Wikilink node
    // inside — a note-transclusion embed renders as its literal markup.
    const doc = 'intro\n\n![[some/note]]\n'
    mountWith(doc, 0)
    expect(imgs()).toHaveLength(0)
    expect(document.querySelector('.cm-content')!.textContent).toContain('![[some/note]]')
  })

  it('cursor touching the bang reveals the raw embed', () => {
    const doc = 'intro\n\n![[pic.png]]\n'
    const bangPos = doc.indexOf('![[') + 1 // inside the run, on the bang
    mountWith(doc, bangPos)
    expect(imgs()).toHaveLength(0)
    expect(document.querySelector('.cm-content')!.textContent).toContain('![[pic.png]]')
  })
})
