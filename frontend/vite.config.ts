/// <reference types="vitest" />
import { defineConfig, type Plugin } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Top-level browser nav to any non-Vite-internal URL should drop the user
// inside the SPA so shortcuts and switchers stay live. The backend already
// does this via Sec-Fetch-Dest in pages.py, but in dev Vite proxies the URL
// straight through and the backend's bare SPA shell is missing the dev
// bootstrap. This middleware intercepts the doc-fetch before the proxy and
// rewrites the URL to /index.html so Vite serves its own (script-tagged)
// shell. Sub-resource fetches (Sec-Fetch-Dest=iframe/image/...) are left
// alone — they continue through the proxy to the backend's FileResponse
// when the URL looks like an asset. Any URL is fair game except Vite-owned
// paths (the dev client, modules, favicon, internal proxies).
const spaDocFallback: Plugin = {
  name: 'spa-doc-fallback',
  configureServer(server) {
    server.middlewares.use((req, _res, next) => {
      const url = req.url ?? ''
      const path = url.split('?')[0].split('#')[0]
      const isInternalVitePath =
        /^\/(?:@|src\/|node_modules\/|favicon\.svg|vite\.svg|api|ws|index\.html)/.test(path)
      const dest = req.headers['sec-fetch-dest']
      if (!isInternalVitePath && dest === 'document') {
        req.url = '/index.html'
      }
      next()
    })
  },
}

export default defineConfig({
  plugins: [react(), spaDocFallback],
  server: {
    // Bind dual-stack, not the default `localhost`, which on Node 17+
    // resolves to ::1 only and leaves 127.0.0.1 unbound. Safari is the
    // browser that cares: its fetch falls back from the refused IPv4
    // loopback slowly (REST feels seconds-slow) and its WebSocket stack
    // often doesn't fall back at all (CRDT sync never connects). Chrome
    // happy-eyeballs its way to ::1 and hides the problem.
    host: true,
    // `changeOrigin` stays FALSE so the proxy forwards the browser's original
    // `Host` (localhost:5173) rather than rewriting it to the target. The
    // backend OriginGuard authorizes a request by matching `Origin` against
    // `Host` — there's no configured canonical origin (see security.py) — so a
    // rewritten Host makes Origin≠Host and 403s every /api + /ws call. This
    // mirrors the prod contract: the reverse proxy must preserve Host.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true, changeOrigin: false },
      // Forward asset bytes to the backend. The middleware above already
      // rewrote document-dest requests to /index.html, so this proxy only
      // ever sees iframe/image/video/etc. fetches that genuinely want the
      // raw file. `/index.html` is excluded so the post-rewrite request
      // stays on the Vite dev server (which serves the local SPA shell).
      '^/(?!@|src/|node_modules/|favicon\\.svg|vite\\.svg|index\\.html$)[^?#]+\\.(png|jpe?g|gif|svg|webp|ico|avif|bmp|pdf|mp[34]|webm|wav|ogg|flac|m4a|mov|zip|tar|gz|7z|csv|tsv|xml|yaml|yml|toml|txt|html?)$':
        { target: 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
  test: {
    environment: 'jsdom',
    // `mdshards.test` is a synthetic, unresolvable hostname — gives us
    // a valid origin for fetch URL parsing without making jsdom/undici
    // attempt real upgrades that produce event-class mismatch warnings.
    environmentOptions: { jsdom: { url: 'http://mdshards.test/' } },
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
    server: {
      // ixora's compiled output uses extension-less internal imports that
      // strict ESM rejects; inlining forces vitest to transform the package.
      deps: { inline: ['@retronav/ixora'] },
    },
  },
})
