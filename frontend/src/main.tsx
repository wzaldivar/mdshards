import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import './style.css'
import { App } from './App'
import { loadConfig } from './lib/config'

const rootEl = document.getElementById('app')
if (!rootEl) throw new Error('#app element missing from index.html')
const root = createRoot(rootEl)

// Block the initial mount on `/api/config` so React Router boots with
// the correct `basename` — the only piece of deployment-level state the
// frontend cares about. Everything else (API / WS / asset URLs) is at
// the origin's root; the reverse proxy handles the prefix mapping. A
// single Vite-built bundle therefore works at any sub-path without
// rebuilding.
const cfg = await loadConfig()
root.render(
  <StrictMode>
    <BrowserRouter basename={cfg.homePath || undefined}>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
