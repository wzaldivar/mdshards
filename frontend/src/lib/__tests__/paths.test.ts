import { describe, expect, it } from 'vitest'
import { validateVaultPath } from '../paths'

describe('validateVaultPath', () => {
  it('accepts the empty path (root)', () => {
    expect(validateVaultPath('')).toBeNull()
  })

  it('accepts a simple path', () => {
    expect(validateVaultPath('foo/bar')).toBeNull()
  })

  it('rejects spaces', () => {
    expect(validateVaultPath('foo bar')).toBe('spaces are not allowed')
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
})
