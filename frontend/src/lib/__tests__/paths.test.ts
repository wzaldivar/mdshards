import { describe, expect, it } from 'vitest'
import { encodePathToUrl, validateVaultPath } from '../paths'

describe('validateVaultPath', () => {
  it('accepts the empty path (root)', () => {
    expect(validateVaultPath('')).toBeNull()
  })

  it('accepts a simple path', () => {
    expect(validateVaultPath('foo/bar')).toBeNull()
  })

  it('accepts spaces', () => {
    expect(validateVaultPath('foo bar')).toBeNull()
    expect(validateVaultPath('a dir/my note')).toBeNull()
  })

  it('rejects ..', () => {
    expect(validateVaultPath('../etc')).toContain('..')
  })

  it('rejects mid-path ..', () => {
    expect(validateVaultPath('foo/../etc')).toContain('..')
  })

  it('rejects null byte', () => {
    expect(validateVaultPath('foo\0bar')).toBe('null byte in path')
  })

  it('rejects backslash', () => {
    expect(validateVaultPath('foo\\bar')).toBe('backslash in path segment')
  })

  it('strips a leading slash', () => {
    expect(validateVaultPath('/foo')).toBeNull()
  })

  it('accepts dots in segments — the backend disambiguates md/asset by file existence', () => {
    expect(validateVaultPath('notes/my.weekly')).toBeNull()
    expect(validateVaultPath('foo/my.dog.jpg')).toBeNull()
  })

  it('rejects a top-level _mdshards segment (reserved app namespace)', () => {
    expect(validateVaultPath('_mdshards')).toContain('reserved')
    expect(validateVaultPath('_mdshards/api')).toContain('reserved')
    expect(validateVaultPath('/_mdshards/foo')).toContain('reserved')
  })

  it('accepts _mdshards below the top level and the formerly reserved names', () => {
    expect(validateVaultPath('notes/_mdshards')).toBeNull()
    expect(validateVaultPath('assets')).toBeNull()
    expect(validateVaultPath('api/notes')).toBeNull()
    expect(validateVaultPath('ws')).toBeNull()
  })
})

describe('encodePathToUrl', () => {
  it('percent-encodes spaces per segment, preserving slashes', () => {
    expect(encodePathToUrl('a dir/my note')).toBe('a%20dir/my%20note')
  })

  it('leaves plain paths untouched', () => {
    expect(encodePathToUrl('notes/today')).toBe('notes/today')
  })

  it('encodes URL-reserved chars that would otherwise break the path', () => {
    expect(encodePathToUrl('a#b?c')).toBe('a%23b%3Fc')
  })

  it('does not encode the empty path', () => {
    expect(encodePathToUrl('')).toBe('')
  })
})
