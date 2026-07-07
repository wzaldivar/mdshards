import { afterEach, describe, expect, it, vi } from 'vitest'
import { getEditorPrefs, setEditorPref, subscribeEditorPrefs } from '../editor-prefs'

afterEach(() => {
  localStorage.clear()
})

describe('editor-prefs', () => {
  it('defaults every preference to off', () => {
    expect(getEditorPrefs()).toEqual({
      vim: false,
      lineNumbers: false,
      relativeLineNumbers: false,
    })
  })

  it('round-trips each preference through localStorage', () => {
    setEditorPref('vim', true)
    setEditorPref('relativeLineNumbers', true)
    expect(localStorage.getItem('mdshards:vim')).toBe('1')
    expect(localStorage.getItem('mdshards:relativeLineNumbers')).toBe('1')
    expect(getEditorPrefs()).toEqual({
      vim: true,
      lineNumbers: false,
      relativeLineNumbers: true,
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
