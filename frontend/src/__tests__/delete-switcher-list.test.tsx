import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'
import { DeleteSwitcher } from '../components/DeleteSwitcher'

/*
 * Complements delete-switcher-nav.test.tsx (which pins the delete-current →
 * navigate-home rule). This file covers the PICKER itself: the listing
 * (files only, index.md excluded, current file deduped), query filtering
 * and best-match highlighting, arrow-key movement withdrawing an armed
 * confirmation, deleting an unrelated file leaving the view in place, and
 * the endpoint split between notes and assets.
 */

const TREE = {
  name: '',
  path: '',
  type: 'dir',
  children: [
    { name: 'index.md', path: 'index.md', type: 'file' },
    { name: 'alpha.md', path: 'alpha.md', type: 'file' },
    { name: 'pic.png', path: 'pic.png', type: 'file' },
    {
      name: 'notes',
      path: 'notes',
      type: 'dir',
      children: [{ name: 'today.md', path: 'notes/today.md', type: 'file' }],
    },
  ],
}

function LocationProbe() {
  const loc = useLocation()
  return <div data-testid="loc">{loc.pathname}</div>
}

function stubFetch(treeStatus = 200, deleteStatus = 200) {
  const deletes: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/tree')) {
        return Promise.resolve(
          new Response(JSON.stringify(TREE), {
            status: treeStatus,
            headers: { 'content-type': 'application/json' },
          }),
        )
      }
      if (init?.method === 'DELETE') {
        deletes.push(url)
        return Promise.resolve(new Response('{}', { status: deleteStatus }))
      }
      return Promise.resolve(new Response('{}', { status: 200 }))
    }),
  )
  return deletes
}

function renderDelete(currentDocId: string, currentIsMd = true) {
  return render(
    <MemoryRouter initialEntries={['/' + currentDocId]}>
      <DeleteSwitcher open currentDocId={currentDocId} currentIsMd={currentIsMd} onClose={() => {}} />
      <LocationProbe />
    </MemoryRouter>,
  )
}

async function pickerInput(): Promise<HTMLInputElement> {
  return (await screen.findByPlaceholderText(/pick a file to delete/i)) as HTMLInputElement
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('DeleteSwitcher picker', () => {
  it('lists vault files without index.md and without duplicating the open file', async () => {
    stubFetch()
    renderDelete('alpha')
    await pickerInput()
    // "Delete this file (alpha)" pinned; alpha not listed again below.
    await screen.findByText(/delete this file \(alpha\)/i)
    await screen.findByText('notes/today')
    await screen.findByText('pic.png')
    expect(screen.queryByText(/^index$/)).toBeNull()
    // the open file appears only in the pinned entry, never as a plain row
    expect(screen.queryByText(/^alpha$/)).toBeNull()
  })

  it('filters by query and deletes the best match — an asset via /api/assets/', async () => {
    const deletes = stubFetch()
    renderDelete('alpha')
    const input = await pickerInput()
    await screen.findByText('pic.png')
    fireEvent.change(input, { target: { value: 'pic.png' } })
    fireEvent.keyDown(input, { key: 'Enter' }) // arm
    await screen.findByText(/confirm delete/i)
    fireEvent.keyDown(input, { key: 'Enter' }) // commit
    await waitFor(() => expect(deletes).toHaveLength(1))
    expect(deletes[0]).toContain('/api/assets/pic.png')
    // Deleting an unrelated file leaves the current view in place.
    expect(screen.getByTestId('loc').textContent).toBe('/alpha')
  })

  it('deletes a note via /api/files/ with the doc-id form', async () => {
    const deletes = stubFetch()
    renderDelete('alpha')
    const input = await pickerInput()
    await screen.findByText('notes/today')
    fireEvent.change(input, { target: { value: 'notes/today' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await screen.findByText(/confirm delete/i)
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(deletes).toHaveLength(1))
    expect(deletes[0]).toContain('/api/files/notes/today')
  })

  it('arrow keys move the highlight and withdraw an armed confirmation', async () => {
    const deletes = stubFetch()
    renderDelete('alpha')
    const input = await pickerInput()
    await screen.findByText('pic.png')
    fireEvent.keyDown(input, { key: 'Enter' }) // arm on "Delete this file"
    await screen.findByText(/confirm delete/i)
    fireEvent.keyDown(input, { key: 'ArrowDown' }) // moving withdraws
    expect(screen.queryByText(/confirm delete/i)).toBeNull()
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    fireEvent.keyDown(input, { key: 'Enter' }) // re-arm only — no delete yet
    await screen.findByText(/confirm delete/i)
    expect(deletes).toHaveLength(0)
  })

  it('offers no "Delete this file" entry on the home note', async () => {
    stubFetch()
    renderDelete('')
    await pickerInput()
    await screen.findByText('alpha')
    expect(screen.queryByText(/delete this file/i)).toBeNull()
  })

  it('surfaces a tree-fetch failure as an error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new Error('network down'))),
    )
    renderDelete('alpha')
    await screen.findByText(/network down/i)
  })
})
