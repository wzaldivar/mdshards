import { afterEach, describe, expect, it, vi } from 'vitest'
import { getEditorPrefs, setEditorPref, subscribeEditorPrefs } from '../editor-prefs'

afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

/** Pretend the browser is a keyboardless touch device (see lib/touch.ts). */
function stubTouchPrimary(matches: boolean): void {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({
      matches,
      addEventListener: () => {},
      removeEventListener: () => {},
    })),
  )
}

describe('editor-prefs', () => {
  it('defaults every preference to off', () => {
    expect(getEditorPrefs()).toEqual({
      vim: false,
      lineNumbers: false,
      relativeLineNumbers: false,
      centerLine: false,
    })
  })

  it('round-trips each preference through localStorage', () => {
    setEditorPref('vim', true)
    setEditorPref('relativeLineNumbers', true)
    setEditorPref('centerLine', true)
    expect(localStorage.getItem('mdshards:vim')).toBe('1')
    expect(localStorage.getItem('mdshards:relativeLineNumbers')).toBe('1')
    expect(localStorage.getItem('mdshards:centerLine')).toBe('1')
    expect(getEditorPrefs()).toEqual({
      vim: true,
      lineNumbers: false,
      relativeLineNumbers: true,
      centerLine: true,
    })
  })

  it('treats any non-"1" value as off', () => {
    localStorage.setItem('mdshards:lineNumbers', 'true')
    expect(getEditorPrefs().lineNumbers).toBe(false)
  })

  it('notifies subscribers with a fresh snapshot on change', () => {
    const seen: boolean[] = []
    const unsub = subscribeEditorPrefs((p) => seen.push(p.lineNumbers))
    setEditorPref('lineNumbers', true)
    setEditorPref('lineNumbers', false)
    expect(seen).toEqual([true, false])
    unsub()
  })

  it('stops notifying after unsubscribe', () => {
    const fn = vi.fn()
    const unsub = subscribeEditorPrefs(fn)
    unsub()
    setEditorPref('vim', true)
    expect(fn).not.toHaveBeenCalled()
  })

  it('propagates cross-tab changes via the storage event', () => {
    const seen: boolean[] = []
    const unsub = subscribeEditorPrefs((p) => seen.push(p.lineNumbers))
    // Simulate another tab writing the key, then the browser firing `storage`
    // in this tab (jsdom does not auto-fire it for same-context writes).
    localStorage.setItem('mdshards:lineNumbers', '1')
    window.dispatchEvent(new StorageEvent('storage', { key: 'mdshards:lineNumbers' }))
    expect(seen).toEqual([true])
    unsub()
  })

  it('ignores storage events for unrelated keys', () => {
    const fn = vi.fn()
    const unsub = subscribeEditorPrefs(fn)
    window.dispatchEvent(new StorageEvent('storage', { key: 'some-other-app-key' }))
    expect(fn).not.toHaveBeenCalled()
    unsub()
  })
})

describe('editor-prefs on a keyboardless touch device', () => {
  it('clamps the desktop-only prefs off without touching the stored values', () => {
    setEditorPref('vim', true)
    setEditorPref('centerLine', true)
    stubTouchPrimary(true)
    // vim: a buffer stuck in NORMAL swallows every keystroke from a software
    // keyboard and reads as a broken editor.
    expect(getEditorPrefs().vim).toBe(false)
    // centerLine: the software keyboard covers the region the cursor line
    // would be centered into, so centering is meaningless on a phone.
    expect(getEditorPrefs().centerLine).toBe(false)
    // ...but the user's choices survive, so the same profile on a desktop
    // (or a tablet docked to a keyboard) gets both back.
    expect(localStorage.getItem('mdshards:vim')).toBe('1')
    expect(localStorage.getItem('mdshards:centerLine')).toBe('1')
    vi.unstubAllGlobals()
    expect(getEditorPrefs().vim).toBe(true)
    expect(getEditorPrefs().centerLine).toBe(true)
  })

  it('leaves the pointer-agnostic preferences alone', () => {
    setEditorPref('lineNumbers', true)
    setEditorPref('relativeLineNumbers', true)
    setEditorPref('centerLine', true)
    stubTouchPrimary(true)
    expect(getEditorPrefs()).toEqual({
      vim: false,
      // The line-number gutter works the same under any pointer.
      lineNumbers: true,
      relativeLineNumbers: true,
      centerLine: false,
    })
  })
})
