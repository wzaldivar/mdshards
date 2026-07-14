import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'

/*
 * Server-initiated kicks (same FakeProvider harness as
 * editor-readonly-offline.test.tsx):
 *   - 4001 DOC_DELETED: the file is gone — bail to root, don't reconnect.
 *   - 4002 DOC_MOVED, reason in pendingRenames: WE initiated the rename —
 *     stay silent (the RenameSwitcher already navigated) and consume the
 *     suppression entry.
 *   - 4002 DOC_MOVED, foreign reason: someone else moved the doc — surface
 *     the follow banner, and following navigates to the new URL.
 */

const h = vi.hoisted(() => ({ providers: [] as FakeProvider[] }))

interface FakeProvider {
  awareness: unknown
  wsconnected: boolean
  on(evt: string, cb: (a: unknown) => void): void
  emit(evt: string, arg: unknown): void
  connect(): void
  disconnect(): void
  destroy(): void
}

vi.mock('../lib/crdt', async () => {
  const Y = await import('yjs')
  const { Awareness } = await import('y-protocols/awareness')
  return {
    fetchServerConfig: () => Promise.resolve({ gracePeriodSeconds: 30, homePath: '' }),
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
          if (evt === 'status' && arg && typeof arg === 'object' && 'status' in arg) {
            provider.wsconnected = (arg as { status: string }).status === 'connected'
          }
          ;(handlers[evt] ?? []).forEach((cb) => cb(arg))
        },
        connect() {},
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
import { pendingRenames } from '../lib/pending-rename'

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

function LocationProbe() {
  const loc = useLocation()
  return <div data-testid="loc">{loc.pathname}</div>
}

function latestProvider(): FakeProvider {
  const p = h.providers.at(-1)
  if (!p) throw new Error('no provider created yet')
  return p
}

async function renderAt(path: string) {
  stubResolveMd()
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="*" element={<EditorView />} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  )
  await waitFor(() => expect(document.querySelector('.cm-editor')).not.toBeNull())
}

function close(code: number, reason: string) {
  latestProvider().emit('connection-close', { code, reason } as unknown as CloseEvent)
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  pendingRenames.clear()
  h.providers.length = 0
})

describe('server-initiated kicks', () => {
  it('DOC_DELETED (4001) bails to the root', async () => {
    await renderAt('/notes/today')
    close(4001, '')
    await waitFor(() => expect(screen.getByTestId('loc').textContent).toBe('/'))
  })

  it('DOC_MOVED (4002) by US stays silent and consumes the suppression entry', async () => {
    await renderAt('/notes/today')
    pendingRenames.add('notes/tomorrow')
    close(4002, 'notes/tomorrow')
    await waitFor(() => expect(pendingRenames.has('notes/tomorrow')).toBe(false))
    // no follow banner, no forced navigation — the RenameSwitcher owns it
    expect(screen.queryByText(/was moved to/i)).toBeNull()
    expect(screen.getByTestId('loc').textContent).toBe('/notes/today')
  })

  it('DOC_MOVED (4002) by SOMEONE ELSE offers the follow banner', async () => {
    await renderAt('/notes/today')
    close(4002, 'renamed/elsewhere')
    await screen.findByText(/was moved to/i)
    screen.getByText('renamed/elsewhere')
    fireEvent.click(screen.getByRole('button', { name: /follow/i }))
    await waitFor(() =>
      expect(screen.getByTestId('loc').textContent).toBe('/renamed/elsewhere'),
    )
  })
})
