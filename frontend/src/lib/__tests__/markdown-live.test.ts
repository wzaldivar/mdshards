import { describe, expect, it } from 'vitest'
import { markdown } from '@codemirror/lang-markdown'
import { Autolink, Strikethrough, Table, TaskList } from '@lezer/markdown'
import { resolveAssetUrl } from '../markdown-live'
import { Wikilink } from '../wikilink'

describe('resolveAssetUrl', () => {
  it('resolves a sibling asset from a root note', () => {
    expect(resolveAssetUrl('today', 'diagram.png')).toBe('/diagram.png')
  })

  it('resolves a sibling asset from a nested note', () => {
    expect(resolveAssetUrl('notes/today', 'diagram.png')).toBe('/notes/diagram.png')
  })

  it('percent-encodes the note directory (from the raw doc-id) but not the ref', () => {
    // The note's own dir has a literal space → encoded. The ref is authored
    // as a URL already (`%20`) and must NOT be re-encoded (no `%2520`).
    expect(resolveAssetUrl('a note/today', 'pic.png')).toBe('/a%20note/pic.png')
    expect(resolveAssetUrl('blog/post', '../my%20profile/my%20pict.jpeg')).toBe(
      '/my%20profile/my%20pict.jpeg',
    )
  })

  it('handles ../ traversal in the asset ref', () => {
    expect(resolveAssetUrl('notes/sub/today', '../diagram.png')).toBe(
      '/notes/diagram.png',
    )
  })

  it('passes absolute URLs through unchanged', () => {
    expect(resolveAssetUrl('notes/today', 'https://example.com/x.png')).toBe(
      'https://example.com/x.png',
    )
  })

  it('passes site-absolute paths through unchanged', () => {
    expect(resolveAssetUrl('notes/today', '/static/x.png')).toBe('/static/x.png')
  })

  it('passes data: URIs through unchanged (inline bytes, no network)', () => {
    const data = 'data:image/png;base64,iVBORw0KGgo='
    expect(resolveAssetUrl('today', data)).toBe(data)
  })

  it('treats `../` that escapes the vault root as not-found (empty src)', () => {
    // From a root-level note `index`, the parent directory is the vault
    // root — `../foo.png` would step outside the vault entirely. We refuse
    // to silently map that to `/foo.png` (which could be a real, unrelated
    // file in the vault).
    expect(resolveAssetUrl('index', '../foo.png')).toBe('')
    expect(resolveAssetUrl('today', '../foo.png')).toBe('')
    // Same for excess traversal from a nested note.
    expect(resolveAssetUrl('notes/sub/today', '../../../etc/passwd')).toBe('')
  })

  it('`../` that stays inside the vault still resolves', () => {
    // From a nested note, one `../` lands in the parent directory — still
    // inside the vault, so it's a normal sibling-folder reference.
    expect(resolveAssetUrl('notes/sub/today', '../diagram.png')).toBe(
      '/notes/diagram.png',
    )
    expect(resolveAssetUrl('a/b/c/today', '../../d.png')).toBe('/a/d.png')
  })

  it('user scenario: foo.png / bar.png / ../foo.png from `index`', () => {
    // Vault has <vault>/foo.png. index.md references foo.png, bar.png, and
    // ../foo.png — the renderer surfaces the first as in-vault, treats the
    // second as a missing-but-valid path (backend will 404, broken-image
    // icon), and treats the third as out-of-vault (empty src, no fetch).
    expect(resolveAssetUrl('index', 'foo.png')).toBe('/foo.png')
    expect(resolveAssetUrl('index', 'bar.png')).toBe('/bar.png')
    expect(resolveAssetUrl('index', '../foo.png')).toBe('')
  })

  it('blocks protocol-relative //host/... references', () => {
    // `//evil.com/x.png` would otherwise sneak through as same-origin (the
    // browser reads it as `https://evil.com/x.png`).
    expect(resolveAssetUrl('today', '//evil.com/x.png')).toBe('')
  })

  it('blocks file://, javascript:, and other unknown schemes', () => {
    expect(resolveAssetUrl('today', 'file:///etc/passwd')).toBe('')
    expect(resolveAssetUrl('today', 'javascript:alert(1)')).toBe('')
    expect(resolveAssetUrl('today', 'ftp://example.com/x.png')).toBe('')
    expect(resolveAssetUrl('today', 'vbscript:msgbox(1)')).toBe('')
  })
})

describe('markdown parser configuration', () => {
  /** Run the same extension list the Editor wires up. Returns the names of
   *  block-level nodes visited at the top of the tree, so we can assert that
   *  a table parses as a `Table` and NOT as a `HorizontalRule` (which is
   *  what would happen if the Table extension were missing). */
  function topLevelNodes(src: string): string[] {
    const lang = markdown({ extensions: [Table, TaskList, Strikethrough, Autolink, Wikilink] })
    const tree = lang.language.parser.parse(src)
    const names: string[] = []
    tree.iterate({
      enter: (node) => {
        if (node.from === 0 && node.to === src.length && node.name === 'Document') return
        names.push(node.name)
        // Only top-level — don't descend into block contents.
        return false
      },
    })
    return names
  }

  it('parses a GFM table as a Table node, not a HorizontalRule', () => {
    const src = '| h1 | h2 |\n|----|----|\n| a  | b  |\n'
    const nodes = topLevelNodes(src)
    expect(nodes).toContain('Table')
    // Without the Table extension the `---|---|` line would be a
    // HorizontalRule and fragment the table — make sure that doesn't happen.
    expect(nodes).not.toContain('HorizontalRule')
  })

  it('still parses a real horizontal rule (outside a table)', () => {
    const src = 'before\n\n---\n\nafter\n'
    const nodes = topLevelNodes(src)
    expect(nodes).toContain('HorizontalRule')
  })
})
