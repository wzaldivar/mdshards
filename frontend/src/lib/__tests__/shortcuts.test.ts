import { afterEach, describe, expect, it, vi } from 'vitest'
import { bindGlobalShortcuts, bindShortcuts } from '../shortcuts'

function makeHandlers() {
  return {
    openQuickSwitcher: vi.fn(),
    openDeleteSwitcher: vi.fn(),
    openRenameSwitcher: vi.fn(),
    openUploadSwitcher: vi.fn(),
    openEmojiPicker: vi.fn(),
    openOptions: vi.fn(),
  }
}

describe('bindGlobalShortcuts', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('triggers openQuickSwitcher on Cmd/Ctrl-K', () => {
    const h = makeHandlers()
    const unbind = bindGlobalShortcuts(h)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true }))
    expect(h.openQuickSwitcher).toHaveBeenCalledOnce()
    expect(h.openDeleteSwitcher).not.toHaveBeenCalled()
    expect(h.openRenameSwitcher).not.toHaveBeenCalled()
    unbind()
  })

  it('triggers openEmojiPicker on Cmd/Ctrl-E', () => {
    const h = makeHandlers()
    const unbind = bindGlobalShortcuts(h)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'e', metaKey: true }))
    expect(h.openEmojiPicker).toHaveBeenCalledOnce()
    expect(h.openQuickSwitcher).not.toHaveBeenCalled()
    unbind()
  })

  it('triggers openRenameSwitcher on Cmd/Ctrl-Shift-K', () => {
    const h = makeHandlers()
    const unbind = bindGlobalShortcuts(h)
    window.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'K', ctrlKey: true, shiftKey: true }),
    )
    expect(h.openRenameSwitcher).toHaveBeenCalledOnce()
    expect(h.openQuickSwitcher).not.toHaveBeenCalled()
    expect(h.openDeleteSwitcher).not.toHaveBeenCalled()
    unbind()
  })

  it('triggers openDeleteSwitcher on Cmd/Ctrl-Backspace', () => {
    const h = makeHandlers()
    const unbind = bindGlobalShortcuts(h)
    window.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Backspace', code: 'Backspace', metaKey: true }),
    )
    expect(h.openDeleteSwitcher).toHaveBeenCalledOnce()
    expect(h.openQuickSwitcher).not.toHaveBeenCalled()
    expect(h.openRenameSwitcher).not.toHaveBeenCalled()
    unbind()
  })

  it('ignores Cmd-Shift-Backspace', () => {
    const h = makeHandlers()
    const unbind = bindGlobalShortcuts(h)
    window.dispatchEvent(
      new KeyboardEvent('keydown', {
        key: 'Backspace',
        code: 'Backspace',
        metaKey: true,
        shiftKey: true,
      }),
    )
    expect(h.openDeleteSwitcher).not.toHaveBeenCalled()
    unbind()
  })

  it('ignores plain Backspace so editing works', () => {
    const h = makeHandlers()
    const unbind = bindGlobalShortcuts(h)
    window.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Backspace', code: 'Backspace' }),
    )
    expect(h.openDeleteSwitcher).not.toHaveBeenCalled()
    unbind()
  })

  it('triggers openUploadSwitcher on Cmd/Ctrl-U', () => {
    const h = makeHandlers()
    const unbind = bindGlobalShortcuts(h)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'u', metaKey: true }))
    expect(h.openUploadSwitcher).toHaveBeenCalledOnce()
    expect(h.openQuickSwitcher).not.toHaveBeenCalled()
    unbind()
  })

  it('ignores Alt-modified combos so they can pass through to the OS', () => {
    const h = makeHandlers()
    const unbind = bindGlobalShortcuts(h)
    window.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'k', metaKey: true, altKey: true }),
    )
    expect(h.openQuickSwitcher).not.toHaveBeenCalled()
    expect(h.openRenameSwitcher).not.toHaveBeenCalled()
    expect(h.openOptions).not.toHaveBeenCalled()
    unbind()
  })

  it('triggers openOptions on Cmd/Ctrl-Alt-O', () => {
    const h = makeHandlers()
    const unbind = bindGlobalShortcuts(h)
    window.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'o', metaKey: true, altKey: true }),
    )
    expect(h.openOptions).toHaveBeenCalledOnce()
    expect(h.openQuickSwitcher).not.toHaveBeenCalled()
    unbind()
  })

  it('matches Alt-O via e.code (Alt often mangles the produced char)', () => {
    const h = makeHandlers()
    const unbind = bindGlobalShortcuts(h)
    // On macOS, Alt+O yields 'ø' as the key; e.code stays 'KeyO'.
    window.dispatchEvent(
      new KeyboardEvent('keydown', { code: 'KeyO', key: 'ø', ctrlKey: true, altKey: true }),
    )
    expect(h.openOptions).toHaveBeenCalledOnce()
    unbind()
  })

  it('matches K via e.code so non-Latin / dead-key layouts still work', () => {
    const h = makeHandlers()
    const unbind = bindGlobalShortcuts(h)
    window.dispatchEvent(
      new KeyboardEvent('keydown', { code: 'KeyK', key: '˚', metaKey: true }),
    )
    expect(h.openQuickSwitcher).toHaveBeenCalledOnce()
    unbind()
  })

  it('ignores letters without a Cmd/Ctrl modifier', () => {
    const h = makeHandlers()
    const unbind = bindGlobalShortcuts(h)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k' }))
    expect(h.openQuickSwitcher).not.toHaveBeenCalled()
    expect(h.openDeleteSwitcher).not.toHaveBeenCalled()
    expect(h.openRenameSwitcher).not.toHaveBeenCalled()
    unbind()
  })

  it('unbind removes the listener', () => {
    const h = makeHandlers()
    const unbind = bindGlobalShortcuts(h)
    unbind()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true }))
    expect(h.openQuickSwitcher).not.toHaveBeenCalled()
  })

  it('bindShortcuts attaches to an arbitrary target (e.g. iframe document)', () => {
    const h = makeHandlers()
    const iframe = document.createElement('iframe')
    document.body.appendChild(iframe)
    const docu = iframe.contentDocument
    if (!docu) throw new Error('jsdom iframe missing contentDocument')
    const unbind = bindShortcuts(docu, h)
    docu.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true }))
    expect(h.openQuickSwitcher).toHaveBeenCalledOnce()
    unbind()
    docu.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true }))
    expect(h.openQuickSwitcher).toHaveBeenCalledOnce()
  })
})
