import { afterEach, describe, expect, it } from 'vitest'
import { EditorSelection, EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { markdown } from '@codemirror/lang-markdown'
import { Autolink, Strikethrough, Table, TaskList } from '@lezer/markdown'
import { blockquote, codeblock, hideMarks, htmlBlock, lists } from '@retronav/ixora'
import { markdownLive } from '../markdown-live'
import { Wikilink } from '../wikilink'

/*
 * Mount a real CodeMirror EditorView with the same extension stack the
 * Editor component wires up, then assert the widget-based table renderer:
 *   - rows not under the cursor become `TableRowWidget` instances
 *     (a single `<div class="cm-md-table-row">` child per `.cm-line`);
 *   - the header row's widget also has `cm-md-table-header`;
 *   - the `|---|---|` separator row becomes `cm-md-table-separator`;
 *   - the row that DOES contain the cursor falls back to raw markdown source.
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
      markdownLive({ noteDocId: 'test', onNavigate: () => {} }),
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

describe('GFM table widget rendering', () => {
  // Blank line between the table and the following paragraph — without it
  // lezer-markdown's Table parser greedily absorbs `below` as a pipe-less
  // TableRow. (The renderer filters those out too, but the proper GFM form
  // here is a separating blank line.)
  const doc2x2 = '| h1 | h2 |\n|----|----|\n| a  | b  |\n\nbelow\n'
  const cursorBelow = doc2x2.length

  it('header row is rendered as a TableRowWidget with cm-md-table-header', () => {
    mountWith(doc2x2, cursorBelow)
    const header = document.querySelector('.cm-md-table-row.cm-md-table-header')
    expect(header).not.toBeNull()
  })

  it('separator row is rendered as a TableRowWidget with cm-md-table-separator', () => {
    mountWith(doc2x2, cursorBelow)
    const sep = document.querySelector('.cm-md-table-separator')
    expect(sep).not.toBeNull()
    // No `----` text visible — the widget renders an empty container with a
    // CSS-drawn stripe; the raw source is replaced.
    expect(sep!.textContent ?? '').not.toContain('----')
  })

  it('data row is rendered as a TableRowWidget without the header class', () => {
    mountWith(doc2x2, cursorBelow)
    const dataRows = document.querySelectorAll(
      '.cm-md-table-row:not(.cm-md-table-header)',
    )
    expect(dataRows.length).toBe(1)
  })

  it('each row widget carries the column-count inline style on its grid', () => {
    const doc = '| h1 | h2 | h3 |\n|---|---|---|\n| a  | b  | c  |\n\nbelow\n'
    mountWith(doc, doc.length)
    const header = document.querySelector(
      '.cm-md-table-row.cm-md-table-header',
    ) as HTMLElement | null
    expect(header).not.toBeNull()
    expect(header!.getAttribute('style')).toContain('--cm-md-table-cols: repeat(3, 1fr)')
  })

  it('cells of the header carry cm-md-table-cell + actual text (header)', () => {
    mountWith(doc2x2, cursorBelow)
    const headerCells = document.querySelectorAll(
      '.cm-md-table-header .cm-md-table-cell',
    )
    expect(headerCells.length).toBe(2)
    expect(headerCells[0].textContent).toBe('h1')
    expect(headerCells[1].textContent).toBe('h2')
  })

  it('placing the cursor on a data row drops decorations only on that row', () => {
    // Cursor inside `a` (position 26 in `| h1 | h2 |\n|----|----|\n| a  | b  |\n`).
    mountWith('| h1 | h2 |\n|----|----|\n| a  | b  |\n', 26)
    // Header still widget-rendered.
    expect(document.querySelector('.cm-md-table-header')).not.toBeNull()
    // Separator still widget-rendered.
    expect(document.querySelector('.cm-md-table-separator')).not.toBeNull()
    // Only ONE data row exists in the doc; under cursor, so no widget for it.
    expect(document.querySelectorAll('.cm-md-table-row:not(.cm-md-table-header)').length).toBe(0)
    // The line on which the cursor sits shows raw source containing pipes.
    const allLines = document.querySelectorAll('.cm-line')
    // Find the one that still contains "| a  | b  |" as plain text.
    const rawLines = Array.from(allLines).filter((l) => (l.textContent ?? '').includes('| a'))
    expect(rawLines.length).toBe(1)
  })

  it('escaped pipe inside a cell renders as a literal | in the widget', () => {
    const doc = '| a | b\\|c | d |\n|---|---|---|\n\nbelow\n'
    mountWith(doc, doc.length)
    const headerCells = document.querySelectorAll(
      '.cm-md-table-header .cm-md-table-cell',
    )
    expect(headerCells.length).toBe(3)
    expect(headerCells[1].textContent).toBe('b|c')
  })

  it('an empty middle cell still renders as a column (column count preserved)', () => {
    // lezer-markdown only emits TableCell for non-empty content, so deriving
    // cells from the inter-pipe range is what keeps the column count stable.
    const doc = '| a |   | c |\n|---|---|---|\n| 1 | 2 | 3 |\n\nbelow\n'
    mountWith(doc, doc.length)
    const headerCells = document.querySelectorAll(
      '.cm-md-table-header .cm-md-table-cell',
    )
    expect(headerCells.length).toBe(3)
    expect(headerCells[1].textContent).toBe('')
  })

  it('inline code inside a cell renders as <code>, not literal backticks', () => {
    const doc = '| field | type |\n|---|---|\n| `foo` | string |\n\nbelow\n'
    mountWith(doc, doc.length)
    const codeEl = document.querySelector('.cm-md-table-cell > code')
    expect(codeEl).not.toBeNull()
    expect(codeEl!.textContent).toBe('foo')
  })

  it('bold/italic/strikethrough inside a cell get the expected HTML elements', () => {
    const doc = '| **bold** | *italic* | ~~strike~~ |\n|---|---|---|\n| a | b | c |\n\nbelow\n'
    mountWith(doc, doc.length)
    expect(document.querySelector('.cm-md-table-cell > strong')?.textContent).toBe('bold')
    expect(document.querySelector('.cm-md-table-cell > em')?.textContent).toBe('italic')
    expect(document.querySelector('.cm-md-table-cell > del')?.textContent).toBe('strike')
  })

  it('underscore-style bold (__x__) and italic (_x_) also render', () => {
    const doc = '| __bold__ | _italic_ | x |\n|---|---|---|\n| a | b | c |\n\nbelow\n'
    mountWith(doc, doc.length)
    const strongs = document.querySelectorAll('.cm-md-table-cell > strong')
    const ems = document.querySelectorAll('.cm-md-table-cell > em')
    expect(Array.from(strongs).map((s) => s.textContent)).toContain('bold')
    expect(Array.from(ems).map((e) => e.textContent)).toContain('italic')
  })

  it('two separate italics in one cell render as two <em>s, not one big span', () => {
    const doc = '| *a* *b* | x | y |\n|---|---|---|\n| 1 | 2 | 3 |\n\nbelow\n'
    mountWith(doc, doc.length)
    const ems = document.querySelectorAll('.cm-md-table-header .cm-md-table-cell > em')
    expect(ems.length).toBe(2)
    expect(ems[0].textContent).toBe('a')
    expect(ems[1].textContent).toBe('b')
  })

  it('intra-word underscores stay literal (last_charged_at is NOT italicised)', () => {
    const doc = '| last_charged_at | MAX__INT | x |\n|---|---|---|\n| a | b | c |\n\nbelow\n'
    mountWith(doc, doc.length)
    const cells = document.querySelectorAll('.cm-md-table-header .cm-md-table-cell')
    expect(cells[0].textContent).toBe('last_charged_at')
    expect(cells[0].querySelector('em')).toBeNull()
    expect(cells[1].textContent).toBe('MAX__INT')
    expect(cells[1].querySelector('strong')).toBeNull()
  })

  it('**foo_bar** renders as bold (asterisks bold an identifier with intra-word _)', () => {
    const doc = '| **foo_bar** | x | y |\n|---|---|---|\n| 1 | 2 | 3 |\n\nbelow\n'
    mountWith(doc, doc.length)
    const strong = document.querySelector('.cm-md-table-cell > strong')
    expect(strong?.textContent).toBe('foo_bar')
  })

  it('__foo_bar__ renders as bold (underscore bold around an intra-word _)', () => {
    const doc = '| __foo_bar__ | x | y |\n|---|---|---|\n| 1 | 2 | 3 |\n\nbelow\n'
    mountWith(doc, doc.length)
    const strong = document.querySelector('.cm-md-table-cell > strong')
    expect(strong?.textContent).toBe('foo_bar')
  })

  it('the `---` separator inside a table is NOT marked as a horizontal rule', () => {
    const doc = '| h |\n|---|\n| a |\n\nbelow\n'
    mountWith(doc, doc.length)
    expect(document.querySelectorAll('.cm-line.cm-md-hr').length).toBe(0)
  })

  it('a real horizontal rule outside any table still gets cm-md-hr', () => {
    mountWith('before\n\n---\n\nafter\n')
    expect(document.querySelectorAll('.cm-line.cm-md-hr').length).toBe(1)
  })

  it('setext H1 (`text\\n===`) styles the text line with cm-md-h1', () => {
    const doc = 'Heading 1\n=========\n\nbody\n'
    mountWith(doc, doc.length)
    const lines = document.querySelectorAll('.cm-line')
    expect(lines[0].classList.contains('cm-md-h1')).toBe(true)
    // Heading text itself stays visible.
    expect(lines[0].textContent).toContain('Heading 1')
    // The `=========` line below has no h1 class; its HeaderMark content is
    // replaced when cursor is off the heading.
    expect(lines[1].classList.contains('cm-md-h1')).toBe(false)
    expect(lines[1].textContent ?? '').not.toContain('=========')
  })

  it('inline link with title attaches it to the rendered .cm-md-link mark', () => {
    // Internal (vault) target — external links render inert (no .cm-md-link).
    const doc = '[click here](guides/intro "open the site")\n'
    mountWith(doc, doc.length)
    const link = document.querySelector('.cm-md-link') as HTMLElement | null
    expect(link).not.toBeNull()
    expect(link!.getAttribute('data-href')).toBe('guides/intro')
    expect(link!.getAttribute('title')).toBe('open the site')
  })

  it('image with title sets the <img title="…"> attribute', () => {
    const doc = '![alt text](https://example.com/img.png "hover text")\n'
    mountWith(doc, doc.length)
    const img = document.querySelector('img.cm-md-image') as HTMLImageElement | null
    expect(img).not.toBeNull()
    expect(img!.alt).toBe('alt text')
    expect(img!.title).toBe('hover text')
  })

  it(
    'three-image scenario from `index`: foo.png → real <img>, bar.png → ' +
      'real <img> (backend 404s), ../foo.png → labeled <span> placeholder',
    () => {
      // Vault layout in the user's head: index.md and foo.png. The doc
      // references foo.png (exists), bar.png (not yet uploaded), and
      // ../foo.png (out of vault). The mount uses noteDocId='test' here,
      // but the doc-id has no parent dir either way — the parent of both
      // `test` and `index` is the vault root, so `../foo.png` escapes the
      // same way. Cursor parked at end so none of the images is dropped.
      const doc =
        '![one](foo.png)\n\n![two](bar.png)\n\n![three](../foo.png)\n'
      mountWith(doc, doc.length)
      const nodes = document.querySelectorAll('.cm-md-image')
      expect(nodes.length).toBe(3)
      const [one, two, three] = Array.from(nodes) as HTMLElement[]

      // foo.png — vault-resolved, rendered as a real <img> with src.
      expect(one.tagName).toBe('IMG')
      expect((one as HTMLImageElement).getAttribute('src')).toBe('/foo.png')
      expect(one.classList.contains('cm-md-image-missing')).toBe(false)

      // bar.png — also vault-resolved (user might upload later). Same
      // shape as foo.png; the backend is the one that 404s, not us. The
      // browser will show its standard broken-image icon when /bar.png
      // 404s — that's the desired "predefined name / typo" presentation.
      expect(two.tagName).toBe('IMG')
      expect((two as HTMLImageElement).getAttribute('src')).toBe('/bar.png')
      expect(two.classList.contains('cm-md-image-missing')).toBe(false)

      // ../foo.png — escapes the vault. NOT rendered as an <img> at all,
      // so the browser issues no network request. A labeled span placeholder
      // with role="img" carries the alt text and the marker class.
      expect(three.tagName).toBe('SPAN')
      expect(three.classList.contains('cm-md-image-missing')).toBe(true)
      expect(three.getAttribute('role')).toBe('img')
      expect(three.getAttribute('aria-label')).toBe('three')
      expect(three.textContent).toBe('three')
    },
  )

  it('reference-style link `[t][1]` resolves URL + title from its definition', () => {
    const doc =
      '[See the docs][docs]\n\n[docs]: guides/docs "Project docs"\n'
    mountWith(doc, doc.length)
    const link = document.querySelector('.cm-md-link') as HTMLElement | null
    expect(link).not.toBeNull()
    expect(link!.getAttribute('data-href')).toBe('guides/docs')
    expect(link!.getAttribute('title')).toBe('Project docs')
  })

  it('shortcut reference link `[label]` resolves against a matching definition', () => {
    const doc = '[homepage]\n\n[homepage]: home\n'
    mountWith(doc, doc.length)
    const link = document.querySelector('.cm-md-link') as HTMLElement | null
    expect(link).not.toBeNull()
    expect(link!.getAttribute('data-href')).toBe('home')
  })

  it('unresolved reference link stays as raw markdown (no .cm-md-link)', () => {
    const doc = '[broken][no-such-ref]\n'
    mountWith(doc, doc.length)
    expect(document.querySelector('.cm-md-link')).toBeNull()
  })

  it('reference labels match case-insensitively', () => {
    const doc = '[See][DOCS]\n\n[docs]: guides/docs\n'
    mountWith(doc, doc.length)
    const link = document.querySelector('.cm-md-link') as HTMLElement | null
    expect(link).not.toBeNull()
    expect(link!.getAttribute('data-href')).toBe('guides/docs')
  })

  it('setext H2 (`text\\n---`) styles the text line with cm-md-h2 (not as HR)', () => {
    const doc = 'Heading 2\n---------\n\nbody\n'
    mountWith(doc, doc.length)
    const lines = document.querySelectorAll('.cm-line')
    expect(lines[0].classList.contains('cm-md-h2')).toBe(true)
    expect(lines[0].textContent).toContain('Heading 2')
    // The `---` underline is part of the setext heading, NOT a horizontal
    // rule — make sure we don't accidentally hr-decorate the line.
    expect(lines[1].classList.contains('cm-md-hr')).toBe(false)
    expect(document.querySelectorAll('.cm-line.cm-md-hr').length).toBe(0)
  })
})
