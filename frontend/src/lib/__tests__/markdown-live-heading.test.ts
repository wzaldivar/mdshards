import { describe, expect, it } from 'vitest'
import { isValidAtxHeading } from '../markdown-live'

describe('isValidAtxHeading', () => {
  it('accepts a heading at the very top of the document', () => {
    expect(isValidAtxHeading(null, '')).toBe(true)
  })

  it('accepts a heading at the very bottom of the document', () => {
    expect(isValidAtxHeading('', null)).toBe(true)
  })

  it('accepts a heading that is the only line in the document', () => {
    expect(isValidAtxHeading(null, null)).toBe(true)
  })

  it('accepts a heading sandwiched between blank lines', () => {
    expect(isValidAtxHeading('', '')).toBe(true)
  })

  it('treats whitespace-only lines as blank', () => {
    expect(isValidAtxHeading('   ', '\t  ')).toBe(true)
  })

  it('rejects a heading with text immediately above', () => {
    expect(isValidAtxHeading('previous paragraph', '')).toBe(false)
  })

  it('rejects a heading with text immediately below', () => {
    expect(isValidAtxHeading('', 'following paragraph')).toBe(false)
  })

  it('rejects a heading sandwiched in a paragraph', () => {
    expect(isValidAtxHeading('above', 'below')).toBe(false)
  })
})
