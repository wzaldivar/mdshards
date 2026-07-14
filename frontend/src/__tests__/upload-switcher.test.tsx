import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'
import { UploadSwitcher } from '../components/UploadSwitcher'

/*
 * Upload is the ONLY surface allowed to overwrite vault files, and only via
 * the explicit accept-or-rename prompt after a 409. These tests pin the
 * dispatch rule (SOURCE extension decides md-vs-asset), the overwrite
 * handshake on both endpoints, its withdrawal on edit, and the viewability
 * gate on post-upload navigation.
 */

function LocationProbe() {
  const loc = useLocation()
  return <div data-testid="loc">{loc.pathname}</div>
}

function renderUpload(currentDocId: string, file: File | null, onClose = () => {}) {
  return render(
    <MemoryRouter initialEntries={['/' + currentDocId]}>
      <UploadSwitcher open currentDocId={currentDocId} initialFile={file} onClose={onClose} />
      <LocationProbe />
    </MemoryRouter>,
  )
}

interface Call {
  url: string
  json: Record<string, unknown> | null
  form: FormData | null
}

function stubFetch(statuses: number[]) {
  const calls: Call[] = []
  let i = 0
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const isForm = init?.body instanceof FormData
      calls.push({
        url: String(input),
        json: !isForm && init?.body ? JSON.parse(String(init.body)) : null,
        form: isForm ? (init?.body as FormData) : null,
      })
      const status = statuses[Math.min(i++, statuses.length - 1)]
      return Promise.resolve(
        new Response('{}', { status, headers: { 'content-type': 'application/json' } }),
      )
    }),
  )
  return calls
}

async function input(): Promise<HTMLInputElement> {
  return (await screen.findByPlaceholderText(/upload to vault path/i)) as HTMLInputElement
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('UploadSwitcher', () => {
  it("prefills the target with the current note's directory + source filename", async () => {
    stubFetch([200])
    renderUpload('notes/deep/today', new File(['x'], 'pic.png'))
    expect((await input()).value).toBe('notes/deep/pic.png')
    // The resolved-path preview reflects it too.
    await screen.findByText(/will save to/i)
  })

  it('md source uploads via /api/files with the doc-id path and navigates there', async () => {
    const calls = stubFetch([201])
    renderUpload('index', new File(['# hi'], 'note.MD'))
    const el = await input()
    fireEvent.change(el, { target: { value: 'imported/note.md' } })
    fireEvent.keyDown(el, { key: 'Enter' })
    await waitFor(() => expect(screen.getByTestId('loc').textContent).toBe('/imported/note'))
    expect(calls[0].url).toContain('/api/files')
    expect(calls[0].json).toMatchObject({
      path: 'imported/note',
      content: '# hi',
      overwrite: false,
    })
  })

  it('md 409 arms the overwrite offer; the second Enter re-submits with overwrite', async () => {
    const calls = stubFetch([409, 201])
    renderUpload('index', new File(['# hi'], 'note.md'))
    const el = await input()
    fireEvent.keyDown(el, { key: 'Enter' })
    await screen.findByText(/already exists — press Enter again to overwrite/i)
    expect(calls[0].json).toMatchObject({ overwrite: false })
    fireEvent.keyDown(el, { key: 'Enter' })
    await waitFor(() => expect(calls).toHaveLength(2))
    expect(calls[1].json).toMatchObject({ overwrite: true })
  })

  it('editing the path withdraws the overwrite offer (rename half of accept-or-rename)', async () => {
    const calls = stubFetch([409, 409])
    renderUpload('index', new File(['x'], 'pic.png'))
    const el = await input()
    fireEvent.keyDown(el, { key: 'Enter' })
    await screen.findByText(/press Enter again to overwrite/i)
    fireEvent.change(el, { target: { value: 'elsewhere.png' } })
    expect(screen.queryByText(/press Enter again to overwrite/i)).toBeNull()
    fireEvent.keyDown(el, { key: 'Enter' })
    await waitFor(() => expect(calls).toHaveLength(2))
    // The edited path submits WITHOUT the overwrite flag — never silent.
    expect(calls[1].form?.get('overwrite')).toBeNull()
  })

  it('asset source uploads via /api/assets and navigates to viewable assets', async () => {
    const calls = stubFetch([201])
    renderUpload('index', new File(['x'], 'pic.png'))
    const el = await input()
    fireEvent.keyDown(el, { key: 'Enter' })
    await waitFor(() => expect(screen.getByTestId('loc').textContent).toBe('/pic.png'))
    expect(calls[0].url).toContain('/api/assets')
    expect(calls[0].form?.get('path')).toBe('pic.png')
  })

  it('asset 409 accept path appends the overwrite form field', async () => {
    const calls = stubFetch([409, 201])
    renderUpload('index', new File(['x'], 'pic.png'))
    const el = await input()
    fireEvent.keyDown(el, { key: 'Enter' })
    await screen.findByText(/press Enter again to overwrite/i)
    fireEvent.keyDown(el, { key: 'Enter' })
    await waitFor(() => expect(calls).toHaveLength(2))
    expect(calls[1].form?.get('overwrite')).toBe('true')
  })

  it('stays put after uploading a non-viewable asset (download-only types)', async () => {
    const onClose = vi.fn()
    stubFetch([201])
    renderUpload('notes/today', new File(['x'], 'bundle.zip'), onClose)
    const el = await input()
    fireEvent.keyDown(el, { key: 'Enter' })
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(screen.getByTestId('loc').textContent).toBe('/notes/today')
  })

  it('surfaces non-409 failures with the status', async () => {
    stubFetch([500])
    renderUpload('index', new File(['x'], 'pic.png'))
    const el = await input()
    fireEvent.keyDown(el, { key: 'Enter' })
    expect(await screen.findByText(/upload failed: 500/i)).toBeTruthy()
  })

  it('refuses to submit without a file or with an invalid target', async () => {
    const calls = stubFetch([200])
    renderUpload('index', null)
    const el = await input()
    fireEvent.change(el, { target: { value: 'somewhere.png' } })
    fireEvent.keyDown(el, { key: 'Enter' })
    await screen.findByText(/pick a file first/i)
    cleanup()
    renderUpload('index', new File(['x'], 'pic.png'))
    const el2 = await input()
    fireEvent.change(el2, { target: { value: 'bad/../pic.png' } })
    fireEvent.keyDown(el2, { key: 'Enter' })
    await screen.findByText(/illegal path segment/i)
    expect(calls).toHaveLength(0)
  })

  it('closes on Escape', async () => {
    stubFetch([200])
    const onClose = vi.fn()
    renderUpload('index', new File(['x'], 'pic.png'), onClose)
    fireEvent.keyDown(await input(), { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })
})
