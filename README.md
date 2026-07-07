# mdshards

A SilverBullet-inspired markdown vault editor. A FastAPI server owns a directory of plain `.md` files; a React 19 + CodeMirror 6 SPA edits them with CRDT-backed live sync over WebSocket.

See **[FEATURES.md](./FEATURES.md)** for the markdown / editor feature inventory (supported, missing, out of scope) and **[CLAUDE.md](./CLAUDE.md)** for the full architectural spec and load-bearing decisions.

## Dev quick-start

```sh
mise install                          # pins Python 3.13 + Node 22 (LTS)
pip install -r backend/requirements.txt
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

See [FEATURES.md](./FEATURES.md) for the full surface — markdown syntax, editor capabilities, keyboard map, and what's deliberately out of scope.

## Deployment

> **Know what you're running.** There is no authentication. Anyone who can reach
> the server gets full read/write access to the vault — this is like exposing a
> VS Code instance to the world over your filesystem. There is no read-only or
> "safe to browse" mode, and none is planned. Run it on a trusted network.

There are **two supported deployment modes** (below). `BASE_URL` sub-path mounting
is a variant of them, not a third mode. Anything else — the backend on a public
interface, custom auth shims, and so on — is at your own risk and untested.

The frontend is **build-config-agnostic**: `npm run build` emits a single static
`dist/` that works at any origin and any sub-path with no rebuild. Every URL the
bundle requests (`/api/*`, `/ws/*`, `/assets/*`, asset srcs) is origin-rooted;
all deployment config lives on the **backend** as env vars (see
[`backend/.env.example`](./backend/.env.example)) and is handed to the bundle at
runtime via `/api/config`. So the same `dist/` can be served two ways:

### Single container — uvicorn serves everything (recommended)

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

### Behind nginx — static bundle + proxied API/WS

Serve `dist/` as static files from nginx (or any static host) and reverse-proxy
`/api/`, `/ws/`, `/assets/`, and the SPA-shell routes to a backend uvicorn.
Because the bundle emits origin-rooted URLs, nginx just forwards them — there is
no per-deployment rebuild.

### Serving from a sub-path (`https://host/wiki/`)

Set `BASE_URL=/wiki` on the **backend** (env var). It's wired into FastAPI's
`root_path` and surfaced to the bundle as `homePath` via `/api/config`, which the
SPA uses as its React Router basename. The frontend never learns the prefix at
build time. The origin guard accepts same-origin API/WS calls by matching the
browser's `Origin` against the request's `Host` header (scheme-agnostic, so a
TLS-terminating proxy just works) — make sure the proxy forwards the browser's
`Host` header, as nginx/Caddy/Traefik do by default.

## Tests

```sh
(cd backend && pytest)                # backend (FastAPI + pytest)
npm --prefix frontend run test        # frontend (Vitest)
```
