import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { QuickSwitcher } from '../components/QuickSwitcher'

/*
 * The quick switcher lists the VAULT, not the deployment: even at a
 * sub-path mount (BASE_URL=/wiki → homePath) every row shows the bare
 * vault path — `/`, `foo`, `my/note` — never `/wiki/foo`. The prefix is
 * infrastructure; showing it would misrepresent the vault structure and
 * bloat every row. (User decision 2026-07-14, reversing the earlier
 * qualified-rows behavior.) Navigation still lands under the prefix via
 * React Router's basename. Mock the config accessor to simulate the
 * sub-path deploy and prove the rows ignore it.
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

describe('QuickSwitcher lists bare vault paths under a sub-path deploy', () => {
  it('never qualifies rows with homePath', async () => {
    stubTree()
    render(
      <MemoryRouter>
        <QuickSwitcher open currentDocId="foo/bar" onClose={() => {}} />
      </MemoryRouter>,
    )
    await waitFor(() => expect(document.querySelectorAll('li').length).toBeGreaterThan(0))
    const rows = [...document.querySelectorAll('li')].map((li) => li.textContent)
    expect(rows).toContain('/') // home (index.md)
    expect(rows).toContain('foo')
    expect(rows).toContain('my/note')
    for (const row of rows) expect(row).not.toMatch(/^\/wiki/)
  })
})
