import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'

/*
 * Read-only-past-grace: when the WebSocket connection is lost and the outage
 * outlasts the server's grace window, the editor locks read-only and surfaces
 * the "lost the server" banner (offline is a hard stop, not an offline-editing
 * mode — see CLAUDE.md). A reconnect within grace clears it.
 *
 * We mock ../lib/crdt so we can drive the provider's `status` events directly;
 * the real WebsocketProvider never connects under jsdom, so its events would
 * never fire.
 */

const h = vi.hoisted(() => ({ providers: [] as FakeProvider[] }))

interface FakeProvider {
  awareness: unknown
  wsconnected: boolean
  on(evt: string, cb: (a: unknown) => void): void
  emit(evt: string, arg: unknown): void
  disconnect(): void
  destroy(): void
}

vi.mock('../lib/crdt', async () => {
  const Y = await import('yjs')
  const { Awareness } = await import('y-protocols/awareness')
  return {
    fetchServerConfig: () =>
      Promise.resolve({ gracePeriodSeconds: 30, homePath: '' }),
    openDoc: () => {
      const doc = new Y.Doc()
      const text = doc.getText('content')
      const handlers: Record<string, ((a: unknown) => void)[]> = {}
      const provider: FakeProvider = {
        awareness: new Awareness(doc),
        wsconnected: true,
        on(evt, cb) {
          ;(handlers[evt] ??= []).push(cb)
        },
        emit(evt, arg) {
          ;(handlers[evt] ?? []).forEach((cb) => cb(arg))
        },
        disconnect() {},
        destroy() {},
      }
      h.providers.push(provider)
      return { doc, text, provider }
    },
    closeDoc: () => {},
  }
})

import { EditorView } from '../views/EditorView'

// staleAfterMs = max(5000, grace*1000 - 5000) = 25_000 for a 30s grace.
const STALE_AFTER_MS = 25_000

function stubResolveMd() {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : String(input)
      const m = /\/api\/resolve(?:\/(.*))?$/.exec(url.split('?')[0])
      if (m) {
        return Promise.resolve(
          new Response(JSON.stringify({ type: 'md', canonical: m[1] ?? '' }), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          }),
        )
      }
      return Promise.resolve(new Response('{}', { status: 200 }))
    }),
  )
}

function latestProvider(): FakeProvider {
  const p = h.providers.at(-1)
  if (!p) throw new Error('no provider created yet')
  return p
}

async function renderEditorConnected() {
  render(
    <MemoryRouter initialEntries={['/notes/today']}>
      <Routes>
        <Route path="*" element={<EditorView />} />
      </Routes>
    </MemoryRouter>,
  )
  // Mount + config fetch settle on REAL timers — `waitFor` polls on real
  // timers and would deadlock against a frozen fake clock.
  await waitFor(() => expect(document.querySelector('.cm-editor')).not.toBeNull())
  // First `connected` marks the baseline (everConnected).
  act(() => latestProvider().emit('status', { status: 'connected' }))
  // Only now freeze time, so the grace timer is deterministic.
  vi.useFakeTimers()
}

const bannerRe = /read-only until it's back/i

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
  h.providers.length = 0
})

describe('Editor read-only past grace', () => {
  beforeEach(() => {
    stubResolveMd()
  })

  it('locks read-only and shows the banner once the outage outlasts grace', async () => {
    await renderEditorConnected()
    expect(screen.queryByText(bannerRe)).toBeNull()

    act(() => latestProvider().emit('status', { status: 'disconnected' }))
    // Still within grace → no banner yet.
    act(() => vi.advanceTimersByTime(STALE_AFTER_MS - 1))
    expect(screen.queryByText(bannerRe)).toBeNull()

    // Cross the grace threshold → banner appears, editor is read-only.
    act(() => vi.advanceTimersByTime(1))
    expect(screen.getByText(bannerRe)).toBeDefined()
    expect(
      document.querySelector('.cm-editor .cm-content')?.getAttribute('contenteditable'),
    ).toBe('false')
  })

  it('clears the banner on a reconnect within grace', async () => {
    await renderEditorConnected()

    act(() => latestProvider().emit('status', { status: 'disconnected' }))
    act(() => vi.advanceTimersByTime(STALE_AFTER_MS))
    expect(screen.getByText(bannerRe)).toBeDefined()

    // Reconnect exactly at the threshold → unlock without a remount.
    act(() => latestProvider().emit('status', { status: 'connected' }))
    expect(screen.queryByText(bannerRe)).toBeNull()
    expect(
      document.querySelector('.cm-editor .cm-content')?.getAttribute('contenteditable'),
    ).toBe('true')
  })
})
