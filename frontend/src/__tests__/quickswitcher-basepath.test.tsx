import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { QuickSwitcher } from '../components/QuickSwitcher'

/*
 * When the app is deployed at a sub-path (BASE_URL=/wiki → homePath), the
 * quick switcher must present each row as the URL it actually lives at —
 * `/wiki/`, `/wiki/foo`, `/wiki/my/note` — so the picker reflects where
 * navigation will land. Mock the config accessor to simulate that deploy.
 */
vi.mock('../lib/config', () => ({ getHomePath: () => '/wiki' }))

function stubTree(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            name: '',
            path: '',
            type: 'dir',
            children: [
              { name: 'index.md', path: 'index.md', type: 'file' },
              { name: 'foo.md', path: 'foo.md', type: 'file' },
              {
                name: 'my',
                path: 'my',
                type: 'dir',
                children: [{ name: 'note.md', path: 'my/note.md', type: 'file' }],
              },
            ],
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        ),
      ),
    ),
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('QuickSwitcher reflects the deployment sub-path', () => {
  it('qualifies each displayed row with homePath (/wiki)', async () => {
    stubTree()
    render(
      <MemoryRouter>
        <QuickSwitcher open currentDocId="foo/bar" onClose={() => {}} />
      </MemoryRouter>,
    )
    await waitFor(() => expect(document.querySelectorAll('li').length).toBeGreaterThan(0))
    const rows = [...document.querySelectorAll('li')].map((li) => li.textContent)
    expect(rows).toContain('/wiki/') // home (index.md)
    expect(rows).toContain('/wiki/foo')
    expect(rows).toContain('/wiki/my/note')
  })
})
