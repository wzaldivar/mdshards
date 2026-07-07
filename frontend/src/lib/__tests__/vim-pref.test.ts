import { afterEach, describe, expect, it } from 'vitest'
import { isVimEnabled, setVimEnabled } from '../vim-pref'

afterEach(() => {
  localStorage.clear()
})

describe('vim-pref', () => {
  it('defaults to off when nothing is stored', () => {
    expect(isVimEnabled()).toBe(false)
  })

  it('round-trips the enabled state through localStorage', () => {
    setVimEnabled(true)
    expect(localStorage.getItem('mdshards:vim')).toBe('1')
    expect(isVimEnabled()).toBe(true)
  })

  it('round-trips the disabled state', () => {
    setVimEnabled(true)
    setVimEnabled(false)
    expect(localStorage.getItem('mdshards:vim')).toBe('0')
    expect(isVimEnabled()).toBe(false)
  })

  it('treats any non-"1" value as off', () => {
    localStorage.setItem('mdshards:vim', 'true')
    expect(isVimEnabled()).toBe(false)
  })
})
