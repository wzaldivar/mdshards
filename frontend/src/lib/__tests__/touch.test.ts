import { afterEach, describe, expect, it, vi } from 'vitest'
import { isTouchPrimary, subscribeTouchPrimary } from '../touch'

/** Minimal `matchMedia` stub. Records the query it was asked about so the
 *  tests can assert on the exact capability signal, and exposes `fire()` to
 *  simulate the capability flipping (tablet docked to a keyboard case). */
function stubMatchMedia(matches: boolean) {
  const listeners = new Set<(e: MediaQueryListEvent) => void>()
  const queries: string[] = []
  const mql = {
    matches,
    addEventListener: (_type: string, fn: (e: MediaQueryListEvent) => void) => {
      listeners.add(fn)
    },
    removeEventListener: (_type: string, fn: (e: MediaQueryListEvent) => void) => {
      listeners.delete(fn)
    },
  }
  vi.stubGlobal(
    'matchMedia',
    vi.fn((q: string) => {
      queries.push(q)
      return mql
    }),
  )
  return {
    queries,
    listenerCount: () => listeners.size,
    fire(next: boolean) {
      mql.matches = next
      for (const fn of listeners) fn({ matches: next } as MediaQueryListEvent)
    },
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('touch', () => {
  it('reports desktop when matchMedia is unavailable', () => {
    // jsdom does not implement matchMedia; the keyboard-first desktop
    // behavior must be the safe default rather than a crash.
    expect(window.matchMedia).toBeUndefined()
    expect(isTouchPrimary()).toBe(false)
  })

  it('requires BOTH a coarse pointer and no hover', () => {
    const mm = stubMatchMedia(true)
    expect(isTouchPrimary()).toBe(true)
    // A coarse pointer alone would also match a touchscreen laptop, where the
    // keyboard is present and vim should stay available.
    expect(mm.queries[0]).toBe('(pointer: coarse) and (hover: none)')
  })

  it('reports desktop when the query does not match', () => {
    stubMatchMedia(false)
    expect(isTouchPrimary()).toBe(false)
  })

  it('treats a matchMedia that throws as desktop', () => {
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => {
        throw new Error('unsupported query')
      }),
    )
    expect(isTouchPrimary()).toBe(false)
  })

  it('notifies subscribers when the capability flips, and unsubscribes', () => {
    const mm = stubMatchMedia(false)
    const seen: boolean[] = []
    const unsubscribe = subscribeTouchPrimary((t) => seen.push(t))

    mm.fire(true)
    expect(seen).toEqual([true])

    unsubscribe()
    expect(mm.listenerCount()).toBe(0)
    mm.fire(false)
    expect(seen).toEqual([true]) // no further deliveries
  })

  it('returns a no-op unsubscribe when matchMedia is unavailable', () => {
    expect(() => subscribeTouchPrimary(() => {})()).not.toThrow()
  })
})
