import { describe, expect, it } from 'vitest'
import { parser } from '@lezer/markdown'
import { Highlight } from '../lib/md-highlight'

/** Parse with the Highlight extension and return the node names in order. */
function names(src: string): string[] {
  const p = parser.configure([Highlight])
  const out: string[] = []
  p.parse(src).iterate({
    enter: (n) => {
      out.push(n.name)
    },
  })
  return out
}

describe('Highlight (==text==) extension', () => {
  it('parses a highlight span with its marks', () => {
    const n = names('some ==important== words')
    expect(n).toContain('Highlight')
    expect(n.filter((x) => x === 'HighlightMark')).toHaveLength(2)
  })

  it('does not match a single =', () => {
    expect(names('a =b= c')).not.toContain('Highlight')
  })

  it('does not match runs of three or more =', () => {
    expect(names('a ===b=== c')).not.toContain('Highlight')
  })

  it('does not match an unclosed opener', () => {
    expect(names('a ==b c')).not.toContain('Highlight')
  })

  it('requires flanking like emphasis (no space-padded content)', () => {
    expect(names('a == b == c')).not.toContain('Highlight')
  })

  it('nests inside other inline markup', () => {
    const n = names('**bold ==and marked== text**')
    expect(n).toContain('StrongEmphasis')
    expect(n).toContain('Highlight')
  })
})
