# <img src="docs/logo.svg" alt="" width="30" height="30" align="top"> mdshards

[![CI](https://github.com/wzaldivar/mdshards/actions/workflows/ci.yml/badge.svg)](https://github.com/wzaldivar/mdshards/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/wzaldivar/mdshards/branch/main/graph/badge.svg)](https://codecov.io/gh/wzaldivar/mdshards)
[![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=wzaldivar_mdshards&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=wzaldivar_mdshards)
[![Known Vulnerabilities](https://snyk.io/test/github/wzaldivar/mdshards/badge.svg)](https://snyk.io/test/github/wzaldivar/mdshards)

A SilverBullet-inspired markdown vault editor. A FastAPI server owns a directory of plain `.md` files; a React 19 + CodeMirror 6 SPA edits them with CRDT-backed live sync over WebSocket.

See **[FEATURES.md](./FEATURES.md)** for the markdown / editor feature inventory (supported, missing, out of scope) and **[CLAUDE.md](./CLAUDE.md)** for the full architectural spec and load-bearing decisions.

> **Disclaimer — vibe-coded, maintained accordingly.** The overall design is a
> human decision (see [CLAUDE.md](./CLAUDE.md)), but the implementation has been
> vibe coded. There is no maintenance expectation beyond dependency updates, and
> no intention of adding new features unless something looks really important.
> If you want to take this somewhere, you're probably better off forking it.

## Why mdshards

- **I want a simple tool to edit the notes that live on my LAN server** —
  without sharing them over SMB. I already serve HTTP there; the notes should
  just be one more thing the browser can reach.
- **I want my data to survive any environment.** Plain text (markdown) does
  it flawlessly: no database, no proprietary format, nothing to export. The
  vault is just `.md` files any tool can read.
- **SilverBullet exists — acknowledged.** In fact I used it, ever since
  browser-based shared editing of files became one of my obsessions. But
  recent changes force TLS to deploy on a LAN, and I don't really need a full
  scripting platform. mdshards keeps the part I wanted — the filesystem is
  king, the client is thin — and drops the rest.
- **Why not just Syncthing + local editing with Obsidian?** mdshards is
  actually designed around that: a local Obsidian vault synced with the
  server vault, both sharing changes. But there's a thing offline editors
  don't address — the context switch out of the browser. Deciding which
  browser/profile combination should open a link breaks the flow; following
  it inside the vault's own tab doesn't.

## Dev quick-start

```sh
mise install                          # pins Python 3.13 + Node 22 (LTS)
pip install -r backend/requirements-dev.txt
npm --prefix frontend install
mkdir vault && export VAULT_DIR=$(pwd)/vault

# Two terminals:
(cd backend && uvicorn app.main:app --reload)            # → 127.0.0.1:8000
npm --prefix frontend run dev                            # → 127.0.0.1:5173 (proxies /api + /ws)
```

Open <http://127.0.0.1:5173/>. `<vault>/index.md` is materialized from a placeholder on first hit. From there:

- `Cmd/Ctrl-K` — quick switcher (open or create a note). `Shift+Enter` inside it force-creates at the typed text.
- `Cmd/Ctrl-Shift-K` — rename the current file.
- `Cmd/Ctrl-Backspace` — delete-file picker (confirms before unlinking).
- `Cmd/Ctrl-U` — upload a file into the vault.
- `Cmd/Ctrl-E` — emoji picker (inserts a `:shortcode:` at the cursor).

See [FEATURES.md](./FEATURES.md) for the full surface — markdown syntax, editor capabilities, keyboard map, and what's deliberately out of scope.

## Deployment

> **Know what you're running.** There is no authentication. Anyone who can reach
> the server gets full read/write access to the vault — this is like exposing a
> VS Code instance to the world over your filesystem. There is no read-only or
> "safe to browse" mode, and none is planned. Run it on a trusted network.

There are **three deployment modes**. Mode 1 is the supported one; modes 2 and
3 are provided but at your own risk. `BASE_URL` sub-path mounting is a variant,
not a fourth mode. Anything else — custom auth shims, multi-tenant fronting,
and so on — is untested and on you.

By default the frontend is **build-config-agnostic**: `npm run build` emits a
single static `dist/` that works at any origin and any sub-path with no
rebuild. Every URL the bundle requests (`/api/*`, `/ws/*`, `/assets/*`, asset
srcs) is origin-rooted; deployment config lives on the **backend** as env vars
(see [`backend/.env.example`](./backend/.env.example)) and is handed to the
bundle at runtime via `/api/config`. Mode 3 is the sole, deliberate exception
to that rule.

### Mode 1: single container — uvicorn serves everything (recommended)

The [`Dockerfile`](./Dockerfile) builds `dist/` in a Node stage, then runs
uvicorn as the only process: it serves `/assets/*` and the SPA shell straight
from the bundle and routes `/api/*` + `/ws/*` on the same port. No reverse proxy.

```sh
docker build -t mdshards .
docker run -p 8000:8000 -v "$(pwd)/data":/data mdshards   # → http://127.0.0.1:8000
```

The vault and CRDT cache live under the mounted `/data` volume
(`/data/vault`, `/data/cache`). `index.md` is materialized on first access from
a built-in template. To customize that seed, bind-mount your own markdown file
at `~/.mdshards/index.md` (i.e. `/app/.mdshards/index.md` in the image):

```sh
docker run -p 8000:8000 -v "$(pwd)/data":/data \
  -v "$(pwd)/my-index.md":/app/.mdshards/index.md mdshards
```

It's a fixed path, not an env var, on purpose — a configurable template path
would let the setting read an arbitrary file off the container filesystem.

The app runs as an unprivileged user (default `1000:1000`). When bind-mounting a
host directory, set `UID`/`GID` so the container user matches the host owner and
can write the vault — no rebuild needed:

```sh
docker run -p 8000:8000 -e UID=$(id -u) -e GID=$(id -g) \
  -v "$(pwd)/data":/data mdshards
```

The entrypoint uses these ids only to remap the user and fix `/data` ownership,
then drops privileges — uvicorn itself never runs as root.

### Mode 2: Node front — `vite preview` + `VITE_BACKEND_HOST` (your own risk)

Serve the built bundle with the repo's own Vite server and point it at a
hidden backend via a **runtime env var** — no rebuild, ever:

```sh
npm --prefix frontend run build
VITE_BACKEND_HOST=http://backend:8000 npm --prefix frontend run preview
```

The preview server applies the same routing as dev: top-level document
navigations get the SPA shell, `/api/*` + `/ws/*` + vault-asset fetches are
proxied to `VITE_BACKEND_HOST` with the browser's `Host` preserved (the
origin guard depends on it). Change where the backend lives → restart with a
new value. The backend itself should not be otherwise reachable.

It's the same variable modes 2 and 3 use — seen by `preview` it's a runtime
proxy target, seen by `build` it gets baked into the bundle. Just don't set
it during the `build` step of mode 2.

A containerized version of this mode lives in [`deploy/`](./deploy):
`docker compose -f docker-compose.preview.yml up --build` runs the preview
front + hidden backend pair, and
`VITE_BACKEND_HOST=<url> docker compose -f docker-compose.preview.yml up -d`
retargets the backend with no image rebuild.

### Mode 3: static host — baked backend URL (your own risk, worst)

For a dumb static server that can't proxy, bake the backend origin into the
bundle at **build time**:

```sh
VITE_BACKEND_HOST=https://api.example.com npm --prefix frontend run build
```

Every URL the bundle emits then addresses that host directly. The costs are
yours: **every backend hostname change requires a rebuild**, the backend is
directly exposed to browsers, and the origin guard must still be satisfied —
cross-site fetches are refused, and the WebSocket requires `Origin` to match
the backend's `Host`, so a genuinely different backend origin will refuse
sync unless you arrange otherwise.

Alternatively, skip the baking with a **routing trick**: build unbaked
(origin-rooted URLs) and make your static server proxy the backend surfaces
itself. A verified nginx example lives in [`deploy/`](./deploy) —
`nginx.conf` (the routing rules: `Sec-Fetch-Dest`-based shell-vs-backend
split with a path-shape fallback for plain-HTTP LAN clients — browsers only
send `Sec-Fetch-*` to https/localhost origins — vault-asset fallback,
verbatim `Host` forwarding via `$http_host`),
`nginx.Dockerfile`, and `docker-compose.yml` (the full two-container stack,
`docker compose up --build` from that directory). Also your problem, but a
better one to have.

### Serving from a sub-path (`https://host/wiki/`)

Set `BASE_URL=/wiki` on the **backend** (env var). The app is then fully
contained under the prefix — the proxy needs exactly one rule, forwarding
`/wiki/*` to the backend **with the prefix intact** (never strip it; the
backend strips it itself per ASGI `root_path` semantics). Verified Traefik
shape (single-container image):

```yaml
labels:
  - traefik.http.routers.mdshards.rule=PathPrefix(`/wiki`)
  - traefik.http.services.mdshards.loadbalancer.server.port=8000
```

How it stays rebuild-free: the prefix is applied at **serve time**, never at
build time. The backend rewrites the shell's `src`/`href` bundle refs under
the prefix and injects a `<meta name="mdshards-home-path">` tag; the bundle
reads that meta before its first fetch and prefixes every runtime URL —
`/api/*`, `/ws/*`, vault assets — itself (`lib/backend.ts`). `homePath` from
`/api/config` still drives the React Router basename. The same `dist/`
deploys at `/`, `/wiki`, or anywhere else.

Other services can share the origin freely — mdshards claims nothing
outside `/wiki/`.

The origin guard accepts same-origin API/WS calls by matching the
browser's `Origin` (or, on plain-HTTP LAN origins where browsers omit all
`Sec-Fetch-*` headers, the `Referer`) against the request's `Host` header
(scheme-agnostic, so a TLS-terminating proxy just works) — make sure the proxy
forwards the browser's `Host` header, as nginx/Caddy/Traefik do by default.

## Tests

```sh
(cd backend && pytest)                    # backend (FastAPI + pytest)
(cd backend && pytest --cov=app)          # …with coverage
npm --prefix frontend run test            # frontend (Vitest)
npm --prefix frontend run test:coverage   # …with coverage
pip install -r e2e/requirements.txt
pytest e2e                                # real-browser e2e (needs Docker)
```

The e2e suite builds the shipping Docker image and drives a real Chromium
(`selenium/standalone-chromium` via testcontainers) through actual user
journeys — editing with disk-flush verification, in-note images, the
quick-switcher create flow, and sub-path (`BASE_URL`) containment. It skips
itself when no Docker daemon is reachable.

CI (GitHub Actions) runs both suites with coverage on every push and PR and
reports to Codecov, SonarCloud, and Snyk. Linking those services is a one-time
account step — see **[docs/ci-setup.md](./docs/ci-setup.md)**.

## License

[MIT](./LICENSE). Dependencies are all permissive (MIT / BSD / Apache-2.0 / ISC)
or weak-copyleft that imposes no obligation on this code (MPL-2.0 files consumed
unmodified; the one shipped in the frontend bundle, DOMPurify, is taken under
its Apache-2.0 option).
