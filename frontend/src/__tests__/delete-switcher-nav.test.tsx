import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'
import { DeleteSwitcher } from '../components/DeleteSwitcher'

/*
 * Deleting the OPEN file must navigate to '/'. This used to lean on the
 * Editor's WebSocket close handler (which fires on the DOC_DELETED close code),
 * but Safari/WebKit doesn't surface application-defined WS close codes — it
 * reports 1006 — so that path never fires there. The DeleteSwitcher's own
 * fetch-success navigation is the browser-independent source of truth; these
 * tests lock it in without any WebSocket involved.
 */

function LocationProbe() {
  const loc = useLocation()
  return <div data-testid="loc">{loc.pathname}</div>
}

function renderDelete(currentDocId: string, onClose = () => {}) {
  return render(
    <MemoryRouter initialEntries={['/' + currentDocId]}>
      <DeleteSwitcher open currentDocId={currentDocId} currentIsMd onClose={onClose} />
      <LocationProbe />
    </MemoryRouter>,
  )
}

function stubFetch(deleteStatus = 200) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : String(input)
      if (url.endsWith('/api/tree')) {
        return Promise.resolve(
          new Response(JSON.stringify({ name: '', path: '', type: 'dir', children: [] }), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          }),
        )
      }
      if (init?.method === 'DELETE') {
        return Promise.resolve(new Response('{}', { status: deleteStatus }))
      }
      return Promise.resolve(new Response('{}', { status: 200 }))
    }),
  )
}

async function confirmDeleteCurrent() {
  const input = await screen.findByPlaceholderText(/pick a file to delete/i)
  // First Enter arms the confirm on the highlighted "Delete this file" row.
  fireEvent.keyDown(input, { key: 'Enter' })
  await screen.findByText(/confirm delete/i)
  // Second Enter commits.
  fireEvent.keyDown(input, { key: 'Enter' })
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('DeleteSwitcher navigation', () => {
  beforeEach(() => stubFetch())

  it('navigates to / after deleting the currently-open file', async () => {
    renderDelete('notes/today')
    expect(screen.getByTestId('loc').textContent).toBe('/notes/today')
    await confirmDeleteCurrent()
    await waitFor(() => expect(screen.getByTestId('loc').textContent).toBe('/'))
  })

  it('stays put when the delete request fails', async () => {
    vi.unstubAllGlobals()
    stubFetch(500)
    renderDelete('notes/today')
    await confirmDeleteCurrent()
    // Error surfaces; no navigation away from the file.
    await screen.findByText(/delete failed: 500/i)
    expect(screen.getByTestId('loc').textContent).toBe('/notes/today')
  })
})
