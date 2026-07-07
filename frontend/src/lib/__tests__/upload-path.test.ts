import { describe, expect, it } from 'vitest'
import { finalizeUploadPath, isMarkdownPath, normalizeFilename } from '../upload-path'

describe('finalizeUploadPath', () => {
  it('keeps the source extension when the typed path has none', () => {
    expect(finalizeUploadPath('foo/images/my_dog', 'my_image.png')).toBe(
      'foo/images/my_dog.png',
    )
  })

  it('honors a different typed extension (fully renames)', () => {
    expect(finalizeUploadPath('foo/images/my_dog.jpeg', 'my_image.png')).toBe(
      'foo/images/my_dog.jpeg',
    )
  })

  it('passes through when typed extension matches source', () => {
    expect(finalizeUploadPath('foo/photo.png', 'shot.png')).toBe('foo/photo.png')
  })

  it('strips leading slashes', () => {
    expect(finalizeUploadPath('/foo/bar', 'x.png')).toBe('foo/bar.png')
  })

  it('returns null for empty input', () => {
    expect(finalizeUploadPath('', 'x.png')).toBeNull()
    expect(finalizeUploadPath('   ', 'x.png')).toBeNull()
  })

  describe('md sources: typed extension wins (disk gets .md appended downstream)', () => {
    it('inherits .md when typed has no extension', () => {
      expect(finalizeUploadPath('notes/imported', 'draft.md')).toBe('notes/imported.md')
    })

    it('keeps as-is when typed extension is .md', () => {
      expect(finalizeUploadPath('notes/imported.md', 'draft.md')).toBe('notes/imported.md')
    })

    it('preserves a re-typed non-md extension (UploadSwitcher dispatches by source, not target)', () => {
      // md source, user typed foo.jpeg → finalize keeps foo.jpeg. The
      // UploadSwitcher's md branch then derives docPath=foo.jpeg and the
      // backend writes vault/foo.jpeg.md per the upload-forces-md rule.
      expect(finalizeUploadPath('notes/imported.txt', 'draft.md')).toBe('notes/imported.txt')
      expect(finalizeUploadPath('foo.jpeg', 'foo.md')).toBe('foo.jpeg')
    })
  })

  it('does not treat dots in directory segments as extensions', () => {
    // The "." is part of an interior dir name, not the filename's extension.
    expect(finalizeUploadPath('photo.dir/my_dog', 'shot.png')).toBe('photo.dir/my_dog.png')
  })
})

describe('isMarkdownPath', () => {
  it('matches .md endings', () => {
    expect(isMarkdownPath('foo/bar.md')).toBe(true)
  })
  it('rejects other extensions', () => {
    expect(isMarkdownPath('foo/bar.png')).toBe(false)
    expect(isMarkdownPath('foo/bar')).toBe(false)
  })
})

describe('normalizeFilename', () => {
  it('strips spaces', () => {
    expect(normalizeFilename('My Photo.jpg')).toBe('MyPhoto.jpg')
  })
  it('strips runs of whitespace including tabs and NBSP', () => {
    expect(normalizeFilename('a \t b.png')).toBe('ab.png')
  })
  it('leaves valid filenames untouched', () => {
    expect(normalizeFilename('my_photo.jpg')).toBe('my_photo.jpg')
  })
  it('preserves case', () => {
    expect(normalizeFilename('MyPhoto.JPG')).toBe('MyPhoto.JPG')
  })
  it('preserves dots in basenames — backend disambiguates by file existence', () => {
    expect(normalizeFilename('my.weekly.md')).toBe('my.weekly.md')
    expect(normalizeFilename('my.dog.jpg')).toBe('my.dog.jpg')
    expect(normalizeFilename('archive.tar.gz')).toBe('archive.tar.gz')
  })
})
