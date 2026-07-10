/// <reference types="vitest" />
import { defineConfig, type Plugin } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Where the backend lives, for the DEV server and the PREVIEW server
// (deployment mode 2: `BACKEND_HOST=http://backend:8000 npm run preview`
// serves dist/ with the same proxy rules — runtime env var, no rebuild).
// This is unrelated to VITE_BACKEND_HOST, which BAKES a backend origin into
// the bundle for static hosting (mode 3) — see src/lib/backend.ts.
const BACKEND = process.env.BACKEND_HOST ?? 'http://127.0.0.1:8000'
const BACKEND_WS = BACKEND.replace(/^http/, 'ws')

// Top-level browser nav to any non-Vite-internal URL should drop the user
// inside the SPA so shortcuts and switchers stay live. The backend already
// does this via Sec-Fetch-Dest in pages.py, but the dev/preview server
// proxies the URL straight through and the backend's bare SPA shell is
// missing the bundle's script tags. This middleware intercepts the doc-fetch
// before the proxy and rewrites the URL to /index.html so Vite serves its
// own shell. Sub-resource fetches (Sec-Fetch-Dest=iframe/image/...) are left
// alone — they continue through the proxy to the backend's FileResponse
// when the URL looks like an asset. Any URL is fair game except Vite-owned
// paths (the dev client, modules, favicon, internal proxies).
const docFallbackMiddleware = (server: {
  middlewares: {
    use: (fn: (req: any, res: any, next: () => void) => void) => void
  }
}) => {
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
}

const spaDocFallback: Plugin = {
  name: 'spa-doc-fallback',
  configureServer: docFallbackMiddleware,
  // Same rule for `vite preview` — the deployment-mode-2 front.
  configurePreviewServer: docFallbackMiddleware,
}

// `changeOrigin` stays FALSE so the proxy forwards the browser's original
// `Host` (localhost:5173) rather than rewriting it to the target. The
// backend OriginGuard authorizes a request by matching `Origin` against
// `Host` — there's no configured canonical origin (see security.py) — so a
// rewritten Host makes Origin≠Host and 403s every /api + /ws call. This
// mirrors the prod contract: the reverse proxy must preserve Host.
const proxy = {
  '/api': { target: BACKEND, changeOrigin: false },
  '/ws': { target: BACKEND_WS, ws: true, changeOrigin: false },
  // Forward asset bytes to the backend. The middleware above already
  // rewrote document-dest requests to /index.html, so this proxy only
  // ever sees iframe/image/video/etc. fetches that genuinely want the
  // raw file. `/index.html` is excluded so the post-rewrite request
  // stays on the Vite server (which serves the local SPA shell).
  // Any extensioned path that isn't Vite-owned is a vault asset — the
  // viewer handles arbitrary extensions (browser-default rendering), so
  // the proxy must not enumerate them. The negative lookahead keeps
  // Vite's own URLs (dev client, modules, public/ files, the shell) on
  // the Vite server; the trailing `(\?[^#]*)?` tolerates a query string
  // (AssetViewer appends a `?v=` cache-bust param).
  '^/(?!@|src/|node_modules/|favicon\\.svg|vite\\.svg|index\\.html$)[^?#]+\\.[A-Za-z0-9]+(\\?[^#]*)?$':
    { target: BACKEND, changeOrigin: false },
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
    proxy,
  },
  // Deployment mode 2: `npm run preview` serves the built dist/ with the
  // same routing as dev — BACKEND_HOST decides where /api, /ws, and vault
  // asset fetches go, at runtime, no rebuild.
  preview: {
    host: true,
    proxy,
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
