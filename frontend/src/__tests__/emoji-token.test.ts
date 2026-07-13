import { describe, expect, it } from 'vitest'
import { shortcodeTokenAt } from '../lib/emoji'

describe('shortcodeTokenAt', () => {
  it('finds a half-typed token at the cursor', () => {
    // "say :smi" with cursor at the end
    expect(shortcodeTokenAt('say :smi', 8)).toEqual({ start: 4, end: 8, query: 'smi' })
  })

  it('finds a closed token with the cursor inside', () => {
    // "a :zmile: b" cursor between m and i
    expect(shortcodeTokenAt('a :zmile: b', 5)).toEqual({ start: 2, end: 9, query: 'zmile' })
  })

  it('finds a closed token with the cursor right BEFORE it', () => {
    // `|:smile:` — the cursor sits on the emoji.
    expect(shortcodeTokenAt('a :smile:', 2)).toEqual({ start: 2, end: 9, query: 'smile' })
  })

  it('does NOT match a closed token with the cursor just past it', () => {
    // `:smile:|` — the token is finished; Cmd-E should insert a new one.
    expect(shortcodeTokenAt('a :smile:', 9)).toBeNull()
  })

  it('still matches an unterminated token at its end (mid-typing)', () => {
    // `:foo|`
    expect(shortcodeTokenAt(':foo', 4)).toEqual({ start: 0, end: 4, query: 'foo' })
  })

  it('handles hyphen/sign names', () => {
    expect(shortcodeTokenAt(':t-rex:', 4)).toEqual({ start: 0, end: 7, query: 't-rex' })
    expect(shortcodeTokenAt(':+1:', 3)).toEqual({ start: 0, end: 4, query: '+1' })
  })

  it('returns null when the cursor is elsewhere on the line', () => {
    expect(shortcodeTokenAt('a :smile: b', 11)).toBeNull()
    expect(shortcodeTokenAt('a :smile: b', 1)).toBeNull()
  })


  it('returns null for a bare or empty token', () => {
    expect(shortcodeTokenAt('a : b', 3)).toBeNull()
    expect(shortcodeTokenAt('a :: b', 4)).toBeNull()
  })

  it('returns null on a plain line', () => {
    expect(shortcodeTokenAt('nothing here', 5)).toBeNull()
  })
})
