import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { TouchBar } from '../TouchBar'
import type { ShortcutHandlers } from '../../lib/shortcuts'

function makeHandlers(): ShortcutHandlers & Record<string, ReturnType<typeof vi.fn>> {
  return {
    openQuickSwitcher: vi.fn(),
    openDeleteSwitcher: vi.fn(),
    openRenameSwitcher: vi.fn(),
    openUploadSwitcher: vi.fn(),
    openEmojiPicker: vi.fn(),
    openOptions: vi.fn(),
  }
}

/** The bar binds its actions to `click` (not a pointer event) so VoiceOver /
 *  TalkBack activation and keyboard Enter/Space reach it too; focus is
 *  preserved separately by preventDefault-ing mousedown. Simulate the real
 *  sequence so the focus guard is exercised alongside the action. */
function tap(el: Element): void {
  fireEvent.mouseDown(el)
  fireEvent.click(el)
}

afterEach(() => {
  cleanup()
})

describe('TouchBar', () => {
  it('exposes every keyboard shortcut as a tap target', () => {
    const handlers = makeHandlers()
    render(<TouchBar handlers={handlers} exists currentIsMd />)

    tap(screen.getByLabelText('Open or create a note'))
    tap(screen.getByLabelText('Insert emoji'))
    tap(screen.getByLabelText('Upload a file'))
    tap(screen.getByLabelText('Rename this file'))
    tap(screen.getByLabelText('Delete a file'))
    tap(screen.getByLabelText('Editor options'))

    // Each button drives the SAME handler bag the Cmd/Ctrl keymap does —
    // the bar is a second trigger surface, never a parallel code path.
    expect(handlers.openQuickSwitcher).toHaveBeenCalledOnce()
    expect(handlers.openEmojiPicker).toHaveBeenCalledOnce()
    expect(handlers.openUploadSwitcher).toHaveBeenCalledOnce()
    expect(handlers.openRenameSwitcher).toHaveBeenCalledOnce()
    expect(handlers.openDeleteSwitcher).toHaveBeenCalledOnce()
    expect(handlers.openOptions).toHaveBeenCalledOnce()
  })

  it('does not steal focus from the editor on tap', () => {
    render(<TouchBar handlers={makeHandlers()} exists currentIsMd />)
    // mousedown's default action is what moves focus; suppressing it keeps the
    // caret (and on iOS the software keyboard) in the buffer.
    const prevented = !fireEvent.mouseDown(screen.getByLabelText('Open or create a note'))
    expect(prevented).toBe(true)
  })

  it('disables rename and delete when the path is not a real file', () => {
    const handlers = makeHandlers()
    render(<TouchBar handlers={handlers} exists={false} currentIsMd={false} />)

    const rename = screen.getByLabelText('Rename this file')
    const del = screen.getByLabelText('Delete a file')
    expect((rename as HTMLButtonElement).disabled).toBe(true)
    expect((del as HTMLButtonElement).disabled).toBe(true)

    tap(rename)
    tap(del)
    expect(handlers.openRenameSwitcher).not.toHaveBeenCalled()
    expect(handlers.openDeleteSwitcher).not.toHaveBeenCalled()

    // Open/upload/options stay live on a missing path — that's how the user
    // navigates away from a typo'd URL without a keyboard.
    expect((screen.getByLabelText('Open or create a note') as HTMLButtonElement).disabled).toBe(false)
    expect((screen.getByLabelText('Upload a file') as HTMLButtonElement).disabled).toBe(false)
    expect((screen.getByLabelText('Editor options') as HTMLButtonElement).disabled).toBe(false)
  })

  it('disables the emoji picker on a non-markdown path', () => {
    const handlers = makeHandlers()
    // An asset exists but has no CRDT buffer to insert a shortcode into.
    render(<TouchBar handlers={handlers} exists currentIsMd={false} />)

    const emoji = screen.getByLabelText('Insert emoji')
    expect((emoji as HTMLButtonElement).disabled).toBe(true)
    tap(emoji)
    expect(handlers.openEmojiPicker).not.toHaveBeenCalled()

    expect((screen.getByLabelText('Rename this file') as HTMLButtonElement).disabled).toBe(false)
  })
})
