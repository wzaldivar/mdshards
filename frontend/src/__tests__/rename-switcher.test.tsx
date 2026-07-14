import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'
import { RenameSwitcher } from '../components/RenameSwitcher'
import { pendingRenames } from '../lib/pending-rename'

/*
 * The rename flow is a vault MUTATION — the highest-risk UI surface after
 * delete. These tests pin: endpoint dispatch (md vs asset), the pending-
 * rename WS suppression bookkeeping, the asset→note conversion two-step
 * confirm, failure cleanup, and post-rename navigation (including the
 * converted doc-id the backend returns).
 */

function LocationProbe() {
  const loc = useLocation()
  return <div data-testid="loc">{loc.pathname}</div>
}

function renderRename(currentDocId: string, currentIsMd: boolean, onClose = () => {}) {
  return render(
    <MemoryRouter initialEntries={['/' + currentDocId]}>
      <RenameSwitcher open currentDocId={currentDocId} currentIsMd={currentIsMd} onClose={onClose} />
      <LocationProbe />
    </MemoryRouter>,
  )
}

function stubFetch(status = 200, body: unknown = {}) {
  const calls: { url: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), body: init?.body ? JSON.parse(String(init.body)) : null })
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status,
          headers: { 'content-type': 'application/json' },
        }),
      )
    }),
  )
  return calls
}

async function typeTarget(value: string) {
  const input = await screen.findByPlaceholderText(/rename to/i)
  fireEvent.change(input, { target: { value } })
  return input
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  pendingRenames.clear()
})

describe('RenameSwitcher', () => {
  it('prefills the current doc id and closes on an unchanged Enter without any request', async () => {
    const calls = stubFetch()
    const onClose = vi.fn()
    renderRename('notes/today', true, onClose)
    const input = (await screen.findByPlaceholderText(/rename to/i)) as HTMLInputElement
    expect(input.value).toBe('notes/today')
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(calls).toHaveLength(0)
  })

  it('closes on Escape', async () => {
    stubFetch()
    const onClose = vi.fn()
    renderRename('notes/today', true, onClose)
    const input = await screen.findByPlaceholderText(/rename to/i)
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })

  it('rejects an invalid target locally, without a request', async () => {
    const calls = stubFetch()
    renderRename('notes/today', true)
    const input = await typeTarget('bad/../escape')
    fireEvent.keyDown(input, { key: 'Enter' })
    await screen.findByText(/illegal path segment/i)
    expect(calls).toHaveLength(0)
  })

  it('renames an md note via /api/files/move, tracks pendingRenames, and navigates', async () => {
    const calls = stubFetch(200, { from: 'notes/today', to: 'notes/tomorrow' })
    renderRename('notes/today', true)
    const input = await typeTarget('notes/tomorrow')
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(screen.getByTestId('loc').textContent).toBe('/notes/tomorrow'))
    expect(calls[0].url).toContain('/api/files/move')
    expect(calls[0].body).toEqual({ src: 'notes/today', dst: 'notes/tomorrow' })
    // The initiator marked the destination BEFORE the request so the WS
    // close handler stays silent instead of offering a "follow?" banner.
    expect(pendingRenames.has('notes/tomorrow')).toBe(true)
  })

  it('cleans up pendingRenames and surfaces the error on failure, without navigating', async () => {
    stubFetch(409, { detail: 'destination already exists' })
    renderRename('notes/today', true)
    const input = await typeTarget('notes/taken')
    fireEvent.keyDown(input, { key: 'Enter' })
    await screen.findByText(/rename failed: 409/i)
    expect(pendingRenames.has('notes/taken')).toBe(false)
    expect(screen.getByTestId('loc').textContent).toBe('/notes/today')
  })

  it('renames an asset via /api/assets/move without touching pendingRenames', async () => {
    const calls = stubFetch(200, { from: 'pic.png', to: 'art/pic.png', converted: false })
    renderRename('pic.png', false)
    const input = await typeTarget('art/pic.png')
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(screen.getByTestId('loc').textContent).toBe('/art/pic.png'))
    expect(calls[0].url).toContain('/api/assets/move')
    expect(pendingRenames.size).toBe(0)
  })

  it('percent-encodes spaces only at the URL boundary when navigating', async () => {
    stubFetch(200, { converted: false })
    renderRename('pic.png', false)
    const input = await typeTarget('my pics/my pic.png')
    fireEvent.keyDown(input, { key: 'Enter' })
    // MemoryRouter reports the pathname exactly as navigate() received it —
    // the percent-encoded URL form (a real browser's location bar decodes).
    await waitFor(() =>
      expect(screen.getByTestId('loc').textContent).toBe('/my%20pics/my%20pic.png'),
    )
  })

  it('asset → .md target requires a second Enter and lands on the converted doc-id', async () => {
    const calls = stubFetch(200, { from: 'notes.txt', to: 'notes 2', converted: true })
    renderRename('notes.txt', false)
    const input = await typeTarget('notes 2.md')
    fireEvent.keyDown(input, { key: 'Enter' })
    // First Enter: confirmation prompt, no request yet.
    await screen.findByText(/transform the asset into the note/i)
    expect(calls).toHaveLength(0)
    // Second Enter on the unchanged target commits the conversion.
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(screen.getByTestId('loc').textContent).toBe('/notes%202'))
    expect(calls[0].url).toContain('/api/assets/move')
  })

  it('editing the target withdraws a pending convert confirmation', async () => {
    const calls = stubFetch()
    renderRename('notes.txt', false)
    const input = await typeTarget('notes 2.md')
    fireEvent.keyDown(input, { key: 'Enter' })
    await screen.findByText(/press Enter again to confirm/i)
    // Editing = withdrawing; the prompt disappears and the next Enter
    // starts a FRESH confirmation for the new value rather than committing.
    await typeTarget('other.md')
    expect(screen.queryByText(/press Enter again to confirm/i)).toBeNull()
    fireEvent.keyDown(input, { key: 'Enter' })
    await screen.findByText(/transform the asset into the note "other"/i)
    expect(calls).toHaveLength(0)
  })
})
