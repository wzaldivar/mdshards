import { afterEach, describe, expect, it } from 'vitest'
import { waitFor } from '@testing-library/react'
import {
  consumeModalSentinel,
  hasModalSentinel,
  pushModalSentinel,
} from '../lib/modal-history'

/*
 * The Back-button sentinel (lib/modal-history.ts). On a phone Back is the
 * dismiss gesture, but a modal here is React state rather than a route — so an
 * entry is pushed to give Back something to pop. The invariants that matter:
 * the URL never moves, two modals never stack two entries, and closing by any
 * other means puts the history back exactly as it was (a leftover sentinel
 * silently eats the user's next real Back press).
 */

afterEach(async () => {
  // Leave the history clean for the next test.
  consumeModalSentinel()
  await waitFor(() => expect(hasModalSentinel()).toBe(false))
})

describe('modal history sentinel', () => {
  it('reports no sentinel on an untouched history entry', () => {
    expect(hasModalSentinel()).toBe(false)
  })

  it('pushes an entry that Back can pop, without moving the URL', () => {
    const before = location.href
    pushModalSentinel()
    expect(hasModalSentinel()).toBe(true)
    expect(location.href).toBe(before)
  })

  it('never stacks two sentinels (modal A -> B stays one Back from dismissed)', () => {
    pushModalSentinel()
    const depth = history.length
    pushModalSentinel()
    expect(history.length).toBe(depth)
    expect(hasModalSentinel()).toBe(true)
  })

  it('consuming pops the sentinel back off', async () => {
    pushModalSentinel()
    consumeModalSentinel()
    await waitFor(() => expect(hasModalSentinel()).toBe(false))
  })

  it('consuming with no sentinel is a no-op — it can never eat a real entry', () => {
    const depth = history.length
    const before = location.href
    consumeModalSentinel()
    expect(history.length).toBe(depth)
    expect(location.href).toBe(before)
  })
})
