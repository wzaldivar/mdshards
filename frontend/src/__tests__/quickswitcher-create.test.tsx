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
      if (url.endsWith('/_mdshards/api/tree')) {
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
    expect(posts[0].url).toContain('/_mdshards/api/files')
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

/*
 * DEMO GUARD — the touch surface must not become a second, unguarded way in.
 *
 * The `Create "…"` row is a real button (tap target), so on a phone it, not
 * Shift-Enter, is the create gesture. It therefore has to clear exactly the
 * same demo restrictions the keyboard path does: the 30-char vault path cap
 * (`MAX_VAULT_PATH_LEN`) and the backend's `attachments/` 403. These tests
 * exist so a future touch change can't quietly reopen either.
 */
describe('QuickSwitcher create — touch path honours the demo restrictions', () => {
  it('the create row is a real button, so tapping is a create gesture', async () => {
    const posts = stubFetch(201)
    renderSwitcher()
    const input = await switcherInput()
    fireEvent.change(input, { target: { value: 'tapped' } })
    const row = await screen.findByRole('button', { name: /^Create/ })
    fireEvent.click(row)
    await waitFor(() => expect(screen.getByTestId('loc').textContent).toBe('/tapped'))
    expect(posts[0].body).toEqual({ path: 'tapped' })
  })

  it('an over-cap path is refused on the tap path too — nothing is POSTed', async () => {
    const posts = stubFetch()
    renderSwitcher()
    const input = await switcherInput()
    // 31 chars — one past MAX_VAULT_PATH_LEN. Set on the element directly:
    // the input carries maxLength=30, which is the FIRST guard; this bypasses
    // it deliberately to prove validateVaultPath is a real second one.
    fireEvent.change(input, { target: { value: 'x'.repeat(31) } })
    const row = await screen.findByRole('button', { name: /^Create/ })
    fireEvent.click(row)
    await screen.findByText(/too long/i)
    expect(posts).toHaveLength(0)
  })

  it('caps the typed path at the demo maximum', async () => {
    renderSwitcher()
    const input = await switcherInput()
    // The native maxLength is the first line of defence, so a phone user
    // simply cannot type past the cap.
    expect(input.maxLength).toBe(30)
  })

  it('surfaces the backend attachments/ refusal rather than pretending it worked', async () => {
    // `attachments/` is seeded demo content — the backend 403s any create or
    // move into it. The frontend does not mirror that rule, so the tap path
    // must show the refusal, not navigate as if it had succeeded.
    stubFetch(403)
    renderSwitcher()
    const input = await switcherInput()
    fireEvent.change(input, { target: { value: 'attachments/x.md' } })
    const row = await screen.findByRole('button', { name: /^Create/ })
    fireEvent.click(row)
    await screen.findByText(/create failed: 403/i)
    expect(screen.getByTestId('loc').textContent).toBe('/existing')
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
