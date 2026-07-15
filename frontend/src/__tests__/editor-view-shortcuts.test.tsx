import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router'
import { EditorView } from '../views/EditorView'
import type { ResourceType } from '../lib/use-resolve'

/*
 * End-to-end-ish coverage of the shortcut surface: render the same component
 * tree the live app would for a given URL, dispatch a Cmd-modified keydown on
 * window, assert the matching modal becomes visible.
 *
 * The shortcut binding has broken several times from "unrelated" changes
 * (iframe focus traps, asset routing, render refactors, resolve-aware guards).
 * This test is the canary — if it fails, the four shortcuts are dead in the
 * real app.
 */

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="*" element={<EditorView />} />
      </Routes>
    </MemoryRouter>,
  )
}

function pressShortcut(opts: { key: string; code?: string; shift?: boolean }) {
  fireEvent.keyDown(window, {
    key: opts.key,
    code: opts.code ?? `Key${opts.key.toUpperCase()}`,
    metaKey: true,
    shiftKey: opts.shift ?? false,
  })
}

/** Fire a shortcut and wait for its modal, RE-pressing on each poll. The
 *  handler bag is re-bound in an effect keyed on the resolve result
 *  ([docId, exists, currentIsMd]); a single press right after resolve settles
 *  can land on a briefly-stale binding and be dropped, so one press isn't
 *  reliable under load. Retrying until the placeholder appears closes that
 *  race (and the plain findBy-timeout flake). Reopening an already-open modal
 *  is idempotent. Returns the input so callers can go on to type into it. */
async function openWithShortcut(
  opts: { key: string; code?: string; shift?: boolean },
  placeholder: RegExp,
): Promise<HTMLElement> {
  let el: HTMLElement | null = null
  await waitFor(() => {
    pressShortcut(opts)
    el = screen.getByPlaceholderText(placeholder)
  })
  return el as unknown as HTMLElement
}

/** Wait for the useResolve hook's fetch to settle. The shortcut handlers that
 *  guard on file existence (delete, rename) won't fire until this completes.
 *  Three "ready" signals cover the three branches: CodeMirror's own
 *  `.cm-editor` class for md, an `<img>` for asset (image), and an `<h2>`
 *  for the NotFound card. */
async function waitForResolve() {
  await waitFor(() => {
    const ready =
      document.querySelector('.cm-editor') ||
      document.querySelector('img') ||
      document.querySelector('h2')
    expect(ready).not.toBeNull()
  })
}

/** Stub /api/resolve to return the given type, and /api/tree to return empty.
 *  The canonical field is set to whatever path was asked about so useResolve
 *  doesn't trigger a redirect — these tests cover the "resolved cleanly"
 *  shape, not the canonical-redirect flow (which is exercised separately). */
function stubBackend(resolveType: ResourceType) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : (input as URL).toString()
      const resolveMatch = /\/api\/resolve(?:\/(.*))?$/.exec(url.split('?')[0])
      if (resolveMatch) {
        const canonical = resolveMatch[1] ?? ''
        return Promise.resolve(
          new Response(JSON.stringify({ type: resolveType, canonical }), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          }),
        )
      }
      // /api/tree and friends — return an empty tree so the modals can open.
      return Promise.resolve(
        new Response(
          JSON.stringify({ name: '', path: '', type: 'dir', children: [] }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        ),
      )
    }),
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('EditorView shortcuts on an asset URL', () => {
  beforeEach(() => stubBackend('asset'))

  it('Cmd-K opens the quick switcher', async () => {
    renderAt('/my/photo.jpeg')
    await waitForResolve()
    expect(await openWithShortcut({ key: 'k' }, /go to or create/i)).toBeDefined()
  })

  it('Cmd-Backspace opens the delete switcher', async () => {
    renderAt('/my/photo.jpeg')
    await waitForResolve()
    expect(
      await openWithShortcut({ key: 'Backspace', code: 'Backspace' }, /pick a file to delete/i),
    ).toBeDefined()
  })

  it('Cmd-Shift-K opens the rename switcher', async () => {
    renderAt('/my/photo.jpeg')
    await waitForResolve()
    expect(await openWithShortcut({ key: 'K', shift: true }, /rename to/i)).toBeDefined()
  })

  it('Cmd-U triggers the hidden file picker', async () => {
    renderAt('/my/photo.jpeg')
    await waitForResolve()
    const hiddenInput = document.querySelector<HTMLInputElement>('input[type="file"]')
    expect(hiddenInput).not.toBeNull()
    const clickSpy = vi.spyOn(hiddenInput!, 'click')
    pressShortcut({ key: 'u' })
    expect(clickSpy).toHaveBeenCalledOnce()
    expect(screen.queryByPlaceholderText(/upload to vault path/i)).toBeNull()
  })

  it('Cmd-E does NOT open the emoji picker (no buffer to insert into)', async () => {
    renderAt('/my/photo.jpeg')
    await waitForResolve()
    pressShortcut({ key: 'e' })
    expect(screen.queryByPlaceholderText(/insert emoji/i)).toBeNull()
  })

  it('renders the asset as a real <img>, not an iframe', async () => {
    renderAt('/my/photo.jpeg')
    await waitForResolve()
    // The src carries a per-navigation `?v=` cache-bust param (see
    // AssetViewer) — match on the path prefix, not the exact URL.
    const img = document.querySelector('img[src^="/my/photo.jpeg?v="]')
    expect(img).not.toBeNull()
    expect(document.querySelector('iframe')).toBeNull()
  })
})

describe('EditorView shortcuts on a markdown URL', () => {
  beforeEach(() => stubBackend('md'))

  it('Cmd-E opens the emoji picker', async () => {
    renderAt('/note')
    await waitForResolve()
    expect(await openWithShortcut({ key: 'e' }, /insert emoji/i)).toBeDefined()
  })

  it('Cmd-K opens the quick switcher', async () => {
    renderAt('/notes/today')
    await waitForResolve()
    expect(await openWithShortcut({ key: 'k' }, /go to or create/i)).toBeDefined()
  })

  it('Cmd-Shift-K does NOT open rename on the root index', async () => {
    renderAt('/')
    await waitForResolve()
    pressShortcut({ key: 'K', shift: true })
    expect(screen.queryByPlaceholderText(/rename to/i)).toBeNull()
  })

  it('Cmd-Shift-K opens rename on a non-root note', async () => {
    renderAt('/notes/today')
    await waitForResolve()
    expect(await openWithShortcut({ key: 'K', shift: true }, /rename to/i)).toBeDefined()
  })

  it('Cmd-Shift-K opens rename on a dotty md URL (no false-asset routing)', async () => {
    renderAt('/notes/my.weekly')
    await waitForResolve()
    expect(await openWithShortcut({ key: 'K', shift: true }, /rename to/i)).toBeDefined()
  })

  it('selecting a file shows the disabled-in-demo notice and opens no upload modal', async () => {
    renderAt('/notes/today')
    await waitForResolve()
    const hiddenInput = document.querySelector<HTMLInputElement>('input[type="file"]')!
    const file = new File(['x'], 'My Photo.jpg', { type: 'image/jpeg' })
    Object.defineProperty(hiddenInput, 'files', { value: [file], configurable: true })
    fireEvent.change(hiddenInput)
    // Demo build: uploads are disabled — a notice appears and no modal opens.
    expect(await screen.findByText(/uploads are disabled in this demo/i)).toBeDefined()
    expect(screen.queryByPlaceholderText(/upload to vault path/i)).toBeNull()
  })
})

describe('QuickSwitcher force-create', () => {
  /** Stub /api/resolve to md, /api/tree to a vault containing `my-notes.md`,
   *  and capture POSTs to /api/files so we can assert what was sent. */
  function stubWithTree(): { posts: Array<{ url: URL; body: unknown }> } {
    const posts: Array<{ url: URL; body: unknown }> = []
    // Real vaults always have `index.md` (auto-materialized on startup), so
    // include it here — the QuickSwitcher pins it as the first entry and
    // would otherwise treat it as a creatable target.
    const tree = {
      name: '', path: '', type: 'dir',
      children: [
        { name: 'index.md', path: 'index.md', type: 'file' },
        { name: 'my-notes.md', path: 'my-notes.md', type: 'file' },
        { name: 'my-thoughts.md', path: 'my-thoughts.md', type: 'file' },
      ],
    }
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === 'string' ? input : (input as URL).toString()
        const resolveMatch = /\/api\/resolve(?:\/(.*))?$/.exec(url.split('?')[0])
        if (resolveMatch) {
          const canonical = resolveMatch[1] ?? ''
          return Promise.resolve(
            new Response(JSON.stringify({ type: 'md', canonical }), { status: 200 }),
          )
        }
        if (url.endsWith('/api/files') && init?.method === 'POST') {
          posts.push({
            url: new URL(url, 'http://x'),
            body: JSON.parse(String(init.body)),
          })
          return Promise.resolve(new Response(JSON.stringify({ path: '' }), { status: 201 }))
        }
        return Promise.resolve(
          new Response(JSON.stringify(tree), { status: 200 }),
        )
      }),
    )
    return { posts }
  }

  async function openSwitcherAndType(text: string): Promise<HTMLInputElement> {
    renderAt('/notes/today')
    await waitForResolve()
    const input = (await openWithShortcut({ key: 'k' }, /go to or create/i)) as HTMLInputElement
    fireEvent.change(input, { target: { value: text } })
    // Wait for the tree fetch to settle so matches are populated.
    await waitFor(() => {
      const items = document.querySelectorAll('li')
      expect(items.length).toBeGreaterThan(0)
    })
    return input
  }

  it('plain Enter on "my" navigates to the highlighted match (no POST)', async () => {
    const { posts } = stubWithTree()
    const input = await openSwitcherAndType('my')
    fireEvent.keyDown(input, { key: 'Enter' })
    // Give the click async path a turn to settle; no POST should fire.
    await waitFor(() => expect(posts).toHaveLength(0))
  })

  it('Shift-Enter on "my" creates a new file at "my" (POST /api/files with path=my)', async () => {
    const { posts } = stubWithTree()
    const input = await openSwitcherAndType('my')
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true })
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].url.pathname).toBe('/api/files')
    expect(posts[0].body).toMatchObject({ path: 'my' })
  })

  it('plain Enter on a novel path does NOT create — creation requires Shift-Enter', async () => {
    const { posts } = stubWithTree()
    // "brand-new" matches nothing in the tree, so there is no highlighted match.
    const input = await openSwitcherAndType('brand-new')
    fireEvent.keyDown(input, { key: 'Enter' })
    // No POST should fire — plain Enter is a no-op with no existing match.
    await new Promise((r) => setTimeout(r, 0))
    expect(posts).toHaveLength(0)
  })

  it('Shift-Enter on a novel path creates it', async () => {
    const { posts } = stubWithTree()
    const input = await openSwitcherAndType('brand-new')
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true })
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].body).toMatchObject({ path: 'brand-new' })
  })
})

describe('EditorView shortcuts on a missing URL', () => {
  beforeEach(() => stubBackend('missing'))

  it('renders the NotFound card with a Go home button', async () => {
    renderAt('/no/such/page')
    await waitFor(() => {
      expect(screen.getByText(/not found/i)).toBeDefined()
    })
    expect(screen.getByRole('button', { name: /go home/i })).toBeDefined()
  })

  it('Cmd-K still opens the quick switcher (so the user can navigate away)', async () => {
    renderAt('/no/such/page')
    await waitFor(() => expect(screen.getByText(/not found/i)).toBeDefined())
    expect(await openWithShortcut({ key: 'k' }, /go to or create/i)).toBeDefined()
  })

  it('Cmd-U still triggers the file picker', async () => {
    renderAt('/no/such/page')
    await waitFor(() => expect(screen.getByText(/not found/i)).toBeDefined())
    const hiddenInput = document.querySelector<HTMLInputElement>('input[type="file"]')!
    const clickSpy = vi.spyOn(hiddenInput, 'click')
    pressShortcut({ key: 'u' })
    expect(clickSpy).toHaveBeenCalledOnce()
  })

  it('Cmd-Backspace does NOT open delete (no real file to delete)', async () => {
    renderAt('/no/such/page')
    await waitFor(() => expect(screen.getByText(/not found/i)).toBeDefined())
    pressShortcut({ key: 'Backspace', code: 'Backspace' })
    expect(screen.queryByPlaceholderText(/pick a file to delete/i)).toBeNull()
  })

  it('Cmd-Shift-K does NOT open rename (no real file to rename)', async () => {
    renderAt('/no/such/page')
    await waitFor(() => expect(screen.getByText(/not found/i)).toBeDefined())
    pressShortcut({ key: 'K', shift: true })
    expect(screen.queryByPlaceholderText(/rename to/i)).toBeNull()
  })
})
