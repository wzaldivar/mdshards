import { describe, expect, it } from 'vitest'
import { parser } from '@lezer/markdown'
import { EmojiShortcode } from '../lib/md-emoji'

function names(src: string): string[] {
  const p = parser.configure([EmojiShortcode])
  const out: string[] = []
  p.parse(src).iterate({
    enter: (n) => {
      out.push(n.name)
    },
  })
  return out
}

describe('EmojiShortcode (:code:) extension', () => {
  it('parses simple names', () => {
    expect(names('ship :rocket: now')).toContain('Emoji')
  })

  it('parses hyphenated names (lezer stock parser missed these)', () => {
    expect(names('run :t-rex: run')).toContain('Emoji')
  })

  it('parses signed names like :+1: and :-1:', () => {
    expect(names('lgtm :+1:')).toContain('Emoji')
    expect(names('nope :-1:')).toContain('Emoji')
  })

  it('does not match an unclosed colon', () => {
    expect(names('time: 12:30 pm')).not.toContain('Emoji')
  })

  it('does not match spaces between colons', () => {
    expect(names('a : b : c')).not.toContain('Emoji')
  })
})
