import { describe, expect, it } from 'vitest'
import { routeToDocId } from '../../router'

describe('routeToDocId', () => {
  it('returns "" for the root route', () => {
    expect(routeToDocId(undefined)).toBe('')
    expect(routeToDocId('')).toBe('')
  })

  it('passes through a single-segment route', () => {
    expect(routeToDocId('foo')).toBe('foo')
  })

  it('joins multi-segment routes with /', () => {
    expect(routeToDocId(['foo', 'bar', 'baz'])).toBe('foo/bar/baz')
  })
})
