import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/*
 * config.ts caches at module level (`loaded` / `inflight`), so each test
 * re-imports a fresh module instance via resetModules.
 */

async function freshConfig() {
  vi.resetModules()
  return import('../config')
}

beforeEach(() => {
  vi.resetModules()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('loadConfig', () => {
  it('fetches once, merges defaults, and caches', async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ homePath: '/wiki' }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    const cfg = await freshConfig()
    const first = await cfg.loadConfig()
    // partial payloads merge over defaults
    expect(first).toEqual({ gracePeriodSeconds: 30, homePath: '/wiki' })
    const second = await cfg.loadConfig()
    expect(second).toBe(first)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('dedupes concurrent callers onto one in-flight request', async () => {
    let resolveFetch: (r: Response) => void = () => {}
    const fetchMock = vi.fn(
      () => new Promise<Response>((res) => (resolveFetch = res)),
    )
    vi.stubGlobal('fetch', fetchMock)
    const cfg = await freshConfig()
    const a = cfg.loadConfig()
    const b = cfg.loadConfig()
    resolveFetch(
      new Response(JSON.stringify({ gracePeriodSeconds: 10, homePath: '' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    expect(await a).toEqual(await b)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('falls back to defaults on a non-ok response (degraded root mount)', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response('nope', { status: 500 }))))
    const cfg = await freshConfig()
    expect(await cfg.loadConfig()).toEqual({ gracePeriodSeconds: 30, homePath: '' })
  })

  it('falls back to defaults on a network failure', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('offline'))))
    const cfg = await freshConfig()
    expect(await cfg.loadConfig()).toEqual({ gracePeriodSeconds: 30, homePath: '' })
  })
})

describe('accessors', () => {
  it('getConfig throws before loadConfig resolves; both accessors work after', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify({ gracePeriodSeconds: 5, homePath: '/notes' }), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          }),
        ),
      ),
    )
    const cfg = await freshConfig()
    expect(() => cfg.getConfig()).toThrow(/before loadConfig/)
    // the boot-window-safe accessor reports root until the value lands
    expect(cfg.getHomePath()).toBe('')
    await cfg.loadConfig()
    expect(cfg.getConfig().gracePeriodSeconds).toBe(5)
    expect(cfg.getHomePath()).toBe('/notes')
  })
})
