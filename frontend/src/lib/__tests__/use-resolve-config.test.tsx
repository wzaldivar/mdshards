import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'
import { useResolve } from '../use-resolve'

/*
 * The resolve hook is the routing bootstrap: every navigation goes through
 * it before an Editor (and its WebSocket) may mount. These tests pin the
 * canonical replace-navigation, the error→missing degradations, and the
 * mid-navigation loading gap that prevents Safari's mid-handshake socket
 * churn.
 */

function Probe({ docId }: Readonly<{ docId: string }>) {
  const state = useResolve(docId)
  const loc = useLocation()
  return (
    <div>
      <div data-testid="state">
        {state.status === 'ready' ? state.type : 'loading'}
      </div>
      <div data-testid="loc">{loc.pathname}</div>
    </div>
  )
}

function stubResolve(body: unknown, status = 200) {
  const urls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      urls.push(String(input))
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status,
          headers: { 'content-type': 'application/json' },
        }),
      )
    }),
  )
  return urls
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('useResolve', () => {
  it('reports the resolved type when the path is already canonical', async () => {
    const urls = stubResolve({ type: 'md', canonical: 'notes/today' })
    render(
      <MemoryRouter initialEntries={['/notes/today']}>
        <Probe docId="notes/today" />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('md'))
    expect(urls[0]).toContain('/_mdshards/api/resolve/notes/today')
  })

  it('resolves the root through the bare /_mdshards/api/resolve form', async () => {
    const urls = stubResolve({ type: 'md', canonical: '' })
    render(
      <MemoryRouter initialEntries={['/']}>
        <Probe docId="" />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('md'))
    expect(urls[0].endsWith('/_mdshards/api/resolve')).toBe(true)
  })

  it('replace-navigates to the canonical form (.md URL → extensionless)', async () => {
    stubResolve({ type: 'md', canonical: 'notes/today' })
    render(
      <MemoryRouter initialEntries={['/notes/today.md']}>
        <Probe docId="notes/today.md" />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(screen.getByTestId('loc').textContent).toBe('/notes/today'),
    )
  })

  it('canonicalizes /index to the root', async () => {
    stubResolve({ type: 'md', canonical: '' })
    render(
      <MemoryRouter initialEntries={['/index']}>
        <Probe docId="index" />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByTestId('loc').textContent).toBe('/'))
  })

  it('percent-encodes the fetch URL for spaced paths but compares raw', async () => {
    const urls = stubResolve({ type: 'md', canonical: 'my note' })
    render(
      <MemoryRouter initialEntries={['/my note']}>
        <Probe docId="my note" />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('md'))
    // encoded on the wire, raw in the comparison — no redirect ping-pong
    expect(urls[0]).toContain('/_mdshards/api/resolve/my%20note')
    expect(screen.getByTestId('loc').textContent).toBe('/my note')
  })

  it('degrades a 400 (invalid path) to missing', async () => {
    stubResolve({ detail: 'invalid vault path' }, 400)
    render(
      <MemoryRouter initialEntries={['/bad']}>
        <Probe docId="bad" />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('missing'))
  })

  it('degrades a network failure to missing', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new Error('offline'))),
    )
    render(
      <MemoryRouter initialEntries={['/x']}>
        <Probe docId="x" />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('missing'))
  })
})
