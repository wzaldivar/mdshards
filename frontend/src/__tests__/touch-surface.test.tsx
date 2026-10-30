import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { EditorView } from '../views/EditorView'
import { TouchBar } from '../components/TouchBar'
import { EmojiSwitcher } from '../components/EmojiSwitcher'
import { OptionsPanel } from '../components/OptionsPanel'
import { DeleteSwitcher } from '../components/DeleteSwitcher'
import type { ShortcutHandlers } from '../lib/shortcuts'

/*
 * The keyboardless-touch surface. Every Cmd/Ctrl chord is unreachable on a
 * phone, so `(pointer: coarse) and (hover: none)` swaps in a parallel TRIGGER
 * surface — the TouchBar, the Back-button dismissal, a tappable create row, a
 * tapped emoji mode toggle. jsdom always reports desktop, so none of this runs
 * unless `matchMedia` is stubbed: that stub is what these tests add.
 *
 * The rule these guard is "a parallel trigger surface, never a parallel code
 * path" — each case asserts the touch affordance fires the SAME handler the
 * keyboard one does.
 */

/** Make `lib/touch.ts` report a keyboardless touch device (or not). Must run
 *  before render — `useTouchPrimary` reads it on mount. */
function stubTouchPrimary(matches: boolean): void {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: query.includes('pointer: coarse') ? matches : false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }))
}

/** Minimal backend: /api/resolve answers `md`, everything else an empty tree. */
function stubBackend(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      const resolveMatch = /\/api\/resolve(?:\/(.*))?$/.exec(url.split('?')[0])
      if (resolveMatch) {
        return Promise.resolve(
          new Response(JSON.stringify({ type: 'md', canonical: resolveMatch[1] ?? '' }), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          }),
        )
      }
      return Promise.resolve(
        new Response(JSON.stringify({ name: '', path: '', type: 'dir', children: [] }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      )
    }),
  )
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="*" element={<EditorView />} />
      </Routes>
    </MemoryRouter>,
  )
}

/** Wait for useResolve to settle — the TouchBar's rename/delete buttons are
 *  gated on `exists`, which only lands after the fetch. */
async function waitForResolve() {
  await waitFor(() => {
    expect(document.querySelector('.cm-editor') || document.querySelector('h2')).not.toBeNull()
  })
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('TouchBar on a touch device', () => {
  beforeEach(() => {
    stubTouchPrimary(true)
    stubBackend()
  })

  it('EditorView renders the bar (and desktop does not)', async () => {
    renderAt('/notes/today')
    await waitForResolve()
    expect(await screen.findByRole('navigation', { name: /editor actions/i })).toBeDefined()
  })

  it('is absent on a desktop pointer', async () => {
    stubTouchPrimary(false)
    renderAt('/notes/today')
    await waitForResolve()
    expect(screen.queryByRole('navigation', { name: /editor actions/i })).toBeNull()
  })

  it('tapping 🔍 opens the same quick switcher Cmd-K does', async () => {
    renderAt('/notes/today')
    await waitForResolve()
    fireEvent.click(await screen.findByRole('button', { name: /open or create a note/i }))
    expect(await screen.findByPlaceholderText(/go to or create/i)).toBeDefined()
  })

  it('tapping ⚙️ opens the options panel', async () => {
    renderAt('/notes/today')
    await waitForResolve()
    fireEvent.click(await screen.findByRole('button', { name: /editor options/i }))
    expect(await screen.findByText(/editor options/i)).toBeDefined()
  })

  it('mousedown is suppressed so tapping never blurs the editor', async () => {
    renderAt('/notes/today')
    await waitForResolve()
    const btn = await screen.findByRole('button', { name: /open or create a note/i })
    const ev = new MouseEvent('mousedown', { bubbles: true, cancelable: true })
    btn.dispatchEvent(ev)
    expect(ev.defaultPrevented).toBe(true)
  })
})

describe('TouchBar action gating', () => {
  beforeEach(() => stubTouchPrimary(true))

  const handlers = {
    openQuickSwitcher: vi.fn(),
    openDeleteSwitcher: vi.fn(),
    openRenameSwitcher: vi.fn(),
    openUploadSwitcher: vi.fn(),
    openEmojiPicker: vi.fn(),
    openOptions: vi.fn(),
  } as unknown as ShortcutHandlers

  it('disables rename/delete with no real file, and emoji off a note', () => {
    render(<TouchBar handlers={handlers} exists={false} currentIsMd={false} />)
    for (const name of [/rename this file/i, /delete a file/i, /insert emoji/i]) {
      expect((screen.getByRole('button', { name }) as HTMLButtonElement).disabled).toBe(true)
    }
    // Ungated actions stay live so the user can always navigate away.
    expect(
      (screen.getByRole('button', { name: /open or create a note/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(false)
  })

  it('enables everything on an existing markdown note', () => {
    render(<TouchBar handlers={handlers} exists currentIsMd />)
    for (const name of [/rename this file/i, /delete a file/i, /insert emoji/i]) {
      expect((screen.getByRole('button', { name }) as HTMLButtonElement).disabled).toBe(false)
    }
  })
})

describe('TouchBar keyboard inset', () => {
  /** A stand-in for `window.visualViewport`, which jsdom does not implement.
   *  Real EventTarget so the component's own listeners drive the update. */
  class FakeViewport extends EventTarget {
    height = 800
    offsetTop = 0
  }

  let vv: FakeViewport

  beforeEach(() => {
    stubTouchPrimary(true)
    vv = new FakeViewport()
    vi.stubGlobal('visualViewport', vv)
    Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true })
  })

  const handlers = { openQuickSwitcher: vi.fn() } as unknown as ShortcutHandlers
  const bar = () => screen.getByRole('navigation', { name: /editor actions/i })

  it('sits flat on the bottom while no keyboard is up', () => {
    render(<TouchBar handlers={handlers} exists currentIsMd />)
    expect(bar().style.bottom).toBe('0px')
  })

  it('lifts by the gap the software keyboard opens up', () => {
    render(<TouchBar handlers={handlers} exists currentIsMd />)
    act(() => {
      vv.height = 460
      vv.dispatchEvent(new Event('resize'))
    })
    // 800 layout - (460 visual + 0 offset) = 340px of keyboard.
    expect(bar().style.bottom).toBe('340px')
  })

  it('ignores sub-threshold jitter (browser chrome, not a keyboard)', () => {
    render(<TouchBar handlers={handlers} exists currentIsMd />)
    act(() => {
      vv.height = 790
      vv.dispatchEvent(new Event('resize'))
    })
    expect(bar().style.bottom).toBe('0px')
  })

  it('follows scroll-driven offset changes too', () => {
    render(<TouchBar handlers={handlers} exists currentIsMd />)
    act(() => {
      vv.height = 500
      vv.offsetTop = 40
      vv.dispatchEvent(new Event('scroll'))
    })
    expect(bar().style.bottom).toBe('260px')
  })

  it('unsubscribes on unmount (no update after teardown)', () => {
    const { unmount } = render(<TouchBar handlers={handlers} exists currentIsMd />)
    unmount()
    // Would throw a React "update on unmounted component" path if still bound.
    act(() => {
      vv.height = 400
      vv.dispatchEvent(new Event('resize'))
    })
  })

  it('leaves the bar bottom-anchored where visualViewport is unavailable', () => {
    vi.stubGlobal('visualViewport', undefined)
    render(<TouchBar handlers={handlers} exists currentIsMd />)
    expect(bar().style.bottom).toBe('0px')
  })
})

describe('Back dismisses a modal on touch', () => {
  beforeEach(() => {
    stubTouchPrimary(true)
    stubBackend()
  })

  it('opening a modal pushes a sentinel, and popstate closes it', async () => {
    renderAt('/notes/today')
    await waitForResolve()
    fireEvent.click(await screen.findByRole('button', { name: /open or create a note/i }))
    await screen.findByPlaceholderText(/go to or create/i)
    expect(window.history.state?.mdshardsModal).toBe(true)

    // Back — the phone's dismiss gesture — closes the dialog instead of
    // navigating away from the note.
    act(() => {
      window.dispatchEvent(new PopStateEvent('popstate'))
    })
    await waitFor(() => {
      expect(screen.queryByPlaceholderText(/go to or create/i)).toBeNull()
    })
  })

  it('does not touch history on a desktop pointer (Escape already dismisses)', async () => {
    stubTouchPrimary(false)
    renderAt('/notes/today')
    await waitForResolve()
    fireEvent.keyDown(window, { key: 'k', code: 'KeyK', metaKey: true })
    await screen.findByPlaceholderText(/go to or create/i)
    expect(window.history.state?.mdshardsModal).toBeUndefined()
  })
})

describe('Touch variants of the keyboard-only affordances', () => {
  beforeEach(() => stubTouchPrimary(true))

  it('EmojiSwitcher promotes the Shift modifier to a tappable mode toggle', async () => {
    const onPick = vi.fn()
    render(<EmojiSwitcher open initialQuery="" onPick={onPick} onClose={() => {}} />)
    const input = await screen.findByPlaceholderText(/insert emoji/i)
    fireEvent.change(input, { target: { value: 't-rex' } })
    await screen.findByRole('button', { name: /🦖 :t-rex:/ })

    // `:code:` is armed by default — a tap writes the shortcode, as Enter does.
    const codeBtn = screen.getByRole('button', { name: ':code:' })
    const glyphBtn = screen.getByRole('button', { name: 'glyph' })
    expect(codeBtn.getAttribute('aria-pressed')).toBe('true')
    expect(glyphBtn.getAttribute('aria-pressed')).toBe('false')

    fireEvent.click(glyphBtn)
    expect(glyphBtn.getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(screen.getByRole('button', { name: /🦖 :t-rex:/ }))
    // Same outcome Shift-Enter produces on a keyboard.
    expect(onPick).toHaveBeenCalledWith('t-rex', '🦖', true)
  })

  it('EmojiSwitcher mode toggle switches back to :code:', async () => {
    const onPick = vi.fn()
    render(<EmojiSwitcher open initialQuery="" onPick={onPick} onClose={() => {}} />)
    const input = await screen.findByPlaceholderText(/insert emoji/i)
    fireEvent.change(input, { target: { value: 't-rex' } })
    await screen.findByRole('button', { name: /🦖 :t-rex:/ })
    fireEvent.click(screen.getByRole('button', { name: 'glyph' }))
    fireEvent.click(screen.getByRole('button', { name: ':code:' }))
    fireEvent.click(screen.getByRole('button', { name: /🦖 :t-rex:/ }))
    expect(onPick).toHaveBeenCalledWith('t-rex', '🦖', false)
  })

  it('OptionsPanel hides the desktop-only rows and offers a tappable Close', async () => {
    const onClose = vi.fn()
    render(<OptionsPanel open onClose={onClose} />)
    await screen.findByText(/editor options/i)
    // vim and centre-line are clamped off on touch, so the rows are dropped
    // rather than offered as toggles whose effect is thrown away.
    expect(screen.queryByRole('checkbox', { name: /vim mode/i })).toBeNull()
    expect(screen.queryByRole('checkbox', { name: /center/i })).toBeNull()
    expect(screen.getByRole('checkbox', { name: /show line numbers/i })).toBeDefined()
    // No Escape key here — Close has to be tappable. (The scrim carries an
    // aria-label of its own, so pick the one with visible text.)
    const closeBtn = screen
      .getAllByRole('button', { name: /close/i })
      .find((b) => b.textContent === 'Close')
    expect(closeBtn).toBeDefined()
    fireEvent.click(closeBtn!)
    expect(onClose).toHaveBeenCalled()
  })

  it('OptionsPanel keeps the desktop rows on a desktop pointer', async () => {
    stubTouchPrimary(false)
    render(<OptionsPanel open onClose={() => {}} />)
    await screen.findByText(/editor options/i)
    expect(screen.getByRole('checkbox', { name: /vim mode/i })).toBeDefined()
    // ...and the footer stays the keyboard hint, not a tappable button.
    expect(screen.getByText(/to close/i)).toBeDefined()
  })

  it('DeleteSwitcher names a gesture the device actually has', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              name: '',
              path: '',
              type: 'dir',
              children: [{ name: 'doomed.md', path: 'doomed.md', type: 'file' }],
            }),
            { status: 200, headers: { 'content-type': 'application/json' } },
          ),
        ),
      ),
    )
    render(
      <MemoryRouter>
        <DeleteSwitcher open currentDocId="notes/today" currentIsMd onClose={() => {}} />
      </MemoryRouter>,
    )
    // Rows show the doc-id, so a note lists without its `.md`.
    const row = await screen.findByRole('button', { name: 'doomed' })
    fireEvent.click(row) // arms the confirmation
    expect(await screen.findByText(/\(tap again\)/i)).toBeDefined()
    expect(screen.queryByText(/\(Enter\)/)).toBeNull()
  })
})
