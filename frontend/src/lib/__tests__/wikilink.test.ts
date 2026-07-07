import { describe, expect, it } from 'vitest'
import { parseWikilink, parseWikilinkBody, Wikilink } from '../wikilink'
import { markdown } from '@codemirror/lang-markdown'

describe('parseWikilinkBody', () => {
  it('parses a bare target', () => {
    expect(parseWikilinkBody('notes/today')).toEqual({
      target: 'notes/today',
      alias: null,
    })
  })

  it('parses a target with alias', () => {
    expect(parseWikilinkBody('notes/today|Today')).toEqual({
      target: 'notes/today',
      alias: 'Today',
    })
  })

  it('treats only the first pipe as the separator', () => {
    expect(parseWikilinkBody('foo|a|b')).toEqual({ target: 'foo', alias: 'a|b' })
  })

  it('accepts an empty alias', () => {
    expect(parseWikilinkBody('foo|')).toEqual({ target: 'foo', alias: '' })
  })

  it('rejects empty input', () => {
    expect(parseWikilinkBody('')).toBeNull()
  })

  it('rejects empty target with pipe', () => {
    expect(parseWikilinkBody('|alias')).toBeNull()
  })
})

describe('parseWikilink', () => {
  it('unwraps the outer brackets', () => {
    expect(parseWikilink('[[foo]]')).toEqual({ target: 'foo', alias: null })
    expect(parseWikilink('[[a|b]]')).toEqual({ target: 'a', alias: 'b' })
  })

  it('returns null when brackets are missing', () => {
    expect(parseWikilink('foo')).toBeNull()
    expect(parseWikilink('[[foo]')).toBeNull()
    expect(parseWikilink('[foo]]')).toBeNull()
  })
})

/** Lift just the Wikilink ranges out of the parse tree so the assertions read
 *  directly. */
function wikilinkRanges(src: string): Array<{ from: number; to: number }> {
  const lang = markdown({ extensions: [Wikilink] })
  const tree = lang.language.parser.parse(src)
  const out: Array<{ from: number; to: number }> = []
  tree.iterate({
    enter: (node) => {
      if (node.name === 'Wikilink') out.push({ from: node.from, to: node.to })
    },
  })
  return out
}

describe('Wikilink lezer extension', () => {
  it('captures a single wiki link span', () => {
    expect(wikilinkRanges('see [[foo]] please')).toEqual([{ from: 4, to: 11 }])
  })

  it('captures target|alias forms', () => {
    expect(wikilinkRanges('[[a/b|Label]]')).toEqual([{ from: 0, to: 13 }])
  })

  it('ignores `[[]]` (empty target)', () => {
    expect(wikilinkRanges('[[]] noise')).toEqual([])
  })

  it('does not span across newlines', () => {
    expect(wikilinkRanges('[[foo\nbar]]')).toEqual([])
  })

  it('rejects nested `[[`', () => {
    expect(wikilinkRanges('[[outer [[inner]] ]]')).toEqual([
      // Only the inner one is a valid wikilink.
      { from: 8, to: 17 },
    ])
  })

  it('does not fire inside inline code', () => {
    // Inline code spans skip inline parsing, so [[foo]] should stay literal.
    expect(wikilinkRanges('`[[foo]]`')).toEqual([])
  })

  it('captures two wiki links in the same paragraph', () => {
    expect(wikilinkRanges('[[a]] and [[b/c]]')).toEqual([
      { from: 0, to: 5 },
      { from: 10, to: 17 },
    ])
  })
})
