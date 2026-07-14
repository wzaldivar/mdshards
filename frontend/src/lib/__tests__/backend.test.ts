/** Sub-path containment, runtime half. The backend injects
 *  `<meta name="mdshards-home-path">` into the shell it serves when BASE_URL
 *  is set; every URL the bundle builds must pick the prefix up from it —
 *  and stay origin-rooted when it's absent (root mounts, dev, mode 3). */
import { afterEach, describe, expect, it } from 'vitest'

import { backendUrl, backendWsUrl } from '../backend'

function injectHomePath(prefix: string): void {
  const meta = document.createElement('meta')
  meta.setAttribute('name', 'mdshards-home-path')
  meta.setAttribute('content', prefix)
  document.head.appendChild(meta)
}

afterEach(() => {
  document.head.querySelector('meta[name="mdshards-home-path"]')?.remove()
})

describe('backendUrl', () => {
  it('passes origin-rooted paths through at a root mount (no meta)', () => {
    expect(backendUrl('/api/tree')).toBe('/api/tree')
    expect(backendUrl('/pic.png')).toBe('/pic.png')
  })

  it('prefixes every path with the injected home path', () => {
    injectHomePath('/notes')
    expect(backendUrl('/api/tree')).toBe('/notes/api/tree')
    expect(backendUrl('/assets/index-abc.js')).toBe('/notes/assets/index-abc.js')
    expect(backendUrl('/dir/pic.png?v=1')).toBe('/notes/dir/pic.png?v=1')
  })

  it('treats an empty meta as a root mount', () => {
    injectHomePath('')
    expect(backendUrl('/api/tree')).toBe('/api/tree')
  })
})

describe('backendWsUrl', () => {
  it('derives from the page origin at a root mount', () => {
    expect(backendWsUrl()).toBe('ws://mdshards.test/ws')
  })

  it('carries the injected home path', () => {
    injectHomePath('/notes')
    expect(backendWsUrl()).toBe('ws://mdshards.test/notes/ws')
  })
})
