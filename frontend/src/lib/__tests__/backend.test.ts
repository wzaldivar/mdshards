/** Sub-path containment, runtime half. The backend injects
 *  `<meta name="mdshards-home-path">` into the shell it serves when BASE_URL
 *  is set; every URL the bundle builds must pick the prefix up from it —
 *  and stay origin-rooted when it's absent (root mounts, dev, mode 3).
 *
 *  App-surface URLs (`apiUrl`, `backendWsUrl`) additionally carry the reserved
 *  APP_PREFIX (`/_mdshards`); vault-content URLs (`backendUrl`) never do, so a
 *  vault asset in an `api/` folder stays a plain `/api/...` path. */
import { afterEach, describe, expect, it } from 'vitest'

import { apiUrl, backendUrl, backendWsUrl } from '../backend'

function injectHomePath(prefix: string): void {
  const meta = document.createElement('meta')
  meta.setAttribute('name', 'mdshards-home-path')
  meta.setAttribute('content', prefix)
  document.head.appendChild(meta)
}

afterEach(() => {
  document.head.querySelector('meta[name="mdshards-home-path"]')?.remove()
})

describe('backendUrl (vault content — never APP_PREFIX)', () => {
  it('passes origin-rooted paths through at a root mount (no meta)', () => {
    expect(backendUrl('/pic.png')).toBe('/pic.png')
    // A vault asset in an `api/` folder is a plain path, NOT an app URL.
    expect(backendUrl('/api/pic.png')).toBe('/api/pic.png')
  })

  it('prefixes every path with the injected home path', () => {
    injectHomePath('/notes')
    expect(backendUrl('/pic.png')).toBe('/notes/pic.png')
    expect(backendUrl('/dir/pic.png?v=1')).toBe('/notes/dir/pic.png?v=1')
  })
})

describe('apiUrl (app surface — carries APP_PREFIX)', () => {
  it('adds /_mdshards at a root mount (no meta)', () => {
    expect(apiUrl('/api/tree')).toBe('/_mdshards/api/tree')
  })

  it('adds the injected home path before /_mdshards', () => {
    injectHomePath('/notes')
    expect(apiUrl('/api/tree')).toBe('/notes/_mdshards/api/tree')
  })

  it('treats an empty meta as a root mount', () => {
    injectHomePath('')
    expect(apiUrl('/api/tree')).toBe('/_mdshards/api/tree')
  })
})

describe('backendWsUrl', () => {
  it('derives from the page origin at a root mount', () => {
    expect(backendWsUrl()).toBe('ws://mdshards.test/_mdshards/ws')
  })

  it('carries the injected home path before /_mdshards', () => {
    injectHomePath('/notes')
    expect(backendWsUrl()).toBe('ws://mdshards.test/notes/_mdshards/ws')
  })
})
