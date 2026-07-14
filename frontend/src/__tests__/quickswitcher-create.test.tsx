import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { App } from '../App'
import { NotFound } from '../components/NotFound'
import { QuickSwitcher } from '../components/QuickSwitcher'

/*
 * The quick switcher's CREATE path — the only UI surface that creates vault
 * files implicitly — plus the App route table's /index canonicalization and
 * the NotFound "Go home" action.
 */

const TREE = {
  name: '',
  path: '',
  type: 'dir',
  children: [
    { name: 'index.md', path: 'index.md', type: 'file' },
    { name: 'existing.md', path: 'existing.md', type: 'file' },
  ],
}

function LocationProbe() {
  const loc = useLocation()
  return <div data-testid="loc">{loc.pathname}</div>
}

function stubFetch(createStatus = 201) {
  const posts: { url: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/tree')) {
        return Promise.resolve(
          new Response(JSON.stringify(TREE), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          }),
        )
      }
      if (init?.method === 'POST') {
        posts.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(new Response('{}', { status: createStatus }))
      }
      return Promise.resolve(new Response('{}', { status: 200 }))
    }),
  )
  return posts
}

function renderSwitcher(onClose = () => {}) {
  return render(
    <MemoryRouter initialEntries={['/existing']}>
      <QuickSwitcher open currentDocId="existing" onClose={onClose} />
      <LocationProbe />
    </MemoryRouter>,
  )
}

async function switcherInput(): Promise<HTMLInputElement> {
  return (await screen.findByPlaceholderText(/go to/i)) as HTMLInputElement
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('QuickSwitcher create (Shift-Enter)', () => {
  it('creates the typed path and navigates to it', async () => {
    const posts = stubFetch(201)
    renderSwitcher()
    const input = await switcherInput()
    fireEvent.change(input, { target: { value: 'brand/new note' } })
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true })
    await waitFor(() =>
      expect(screen.getByTestId('loc').textContent).toBe('/brand/new%20note'),
    )
    expect(posts[0].url).toContain('/api/files')
    expect(posts[0].body).toEqual({ path: 'brand/new note' })
  })

  it('surfaces a create failure without navigating', async () => {
    stubFetch(409)
    renderSwitcher()
    const input = await switcherInput()
    fireEvent.change(input, { target: { value: 'clashing' } })
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true })
    await screen.findByText(/create failed: 409/i)
    expect(screen.getByTestId('loc').textContent).toBe('/existing')
  })

  it('rejects an invalid path locally', async () => {
    const posts = stubFetch()
    renderSwitcher()
    const input = await switcherInput()
    fireEvent.change(input, { target: { value: 'bad/../escape' } })
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true })
    await screen.findByText(/illegal path segment/i)
    expect(posts).toHaveLength(0)
  })

  it('plain Enter never creates — it is a no-op with no match', async () => {
    const posts = stubFetch()
    renderSwitcher()
    const input = await switcherInput()
    fireEvent.change(input, { target: { value: 'existing' } }) // current file: hidden from list
    fireEvent.keyDown(input, { key: 'Enter' })
    // dismisses in place; nothing created, nowhere navigated
    await waitFor(() => expect(posts).toHaveLength(0))
    expect(screen.getByTestId('loc').textContent).toBe('/existing')
  })

  it('clicking a row navigates to it', async () => {
    stubFetch()
    renderSwitcher()
    await switcherInput()
    const row = await screen.findByText('/')
    fireEvent.mouseDown(row)
    fireEvent.click(row)
    await waitFor(() => expect(screen.getByTestId('loc').textContent).toBe('/'))
  })
})

describe('App route table', () => {
  it('redirects /index to the canonical root', async () => {
    stubFetch()
    render(
      <MemoryRouter initialEntries={['/index']}>
        <App />
        <LocationProbe />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByTestId('loc').textContent).toBe('/'))
  })
})

describe('NotFound', () => {
  it('shows the missing path and goes home on the button', async () => {
    render(
      <MemoryRouter initialEntries={['/no/such']}>
        <Routes>
          <Route path="*" element={<NotFound path="no/such" />} />
        </Routes>
        <LocationProbe />
      </MemoryRouter>,
    )
    await screen.findByText(/not found/i)
    fireEvent.click(screen.getByRole('button', { name: /go home/i }))
    await waitFor(() => expect(screen.getByTestId('loc').textContent).toBe('/'))
  })
})
