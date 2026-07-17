# Operations: deployment, config & CI

## Configuration (env vars)

All settings are pydantic-settings env vars (or a `.env` file); see `backend/app/config.py` and `backend/.env.example`.

| Var | Default | Purpose |
|---|---|---|
| `VAULT_DIR` | *(required)* | The vault directory of `.md` files. `~` expanded. |
| `CACHE_DIR` | `~/.cache/mdshards` | Binary Yjs cache root (outside the vault). |
| `GRACE_PERIOD_SECONDS` | `30.0` | In-memory doc linger window after last disconnect; also the client read-only threshold. |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | uvicorn **bind** only — not the public URL. |
| `BASE_URL` | `""` (root) | Reverse-proxy sub-path mount (e.g. `/wiki`). |

Static frontend serving is **not** an env var: when a prebuilt bundle exists in a `static/` dir next to the `app/` package, uvicorn serves the SPA shell + `/_mdshards/assets/*` itself; in dev the dir is absent and Vite serves the bundle (`config.py::Settings.static_dir`).

## `BASE_URL` sub-path mounting — serve-time, never build-time

The `dist/` bundle stays base-url-agnostic (the same build deploys at `/`, `/wiki`, anywhere — **no rebuild**). When `BASE_URL` is set, the app is *fully contained* under it:

- `root_path=BASE_URL` on the FastAPI app (`main.py`); per ASGI, incoming paths **include** the prefix and the app strips it — the proxy forwards `<prefix>/*` **unstripped**. That single rule is the whole proxy contract.
- The served shell is rewritten (`pages.py::_prefix_shell`) so bundle refs live under the prefix, and a `<meta name="mdshards-home-path">` is injected. The bundle reads that meta and prefixes every runtime URL through `frontend/src/lib/backend.ts` — this also bootstraps the "which prefix does `/api/config` live under" problem.
- `/api/config`'s `homePath` drives exactly one thing: React Router's `<BrowserRouter basename>`. **Listings always show bare vault paths** (`/`, `foo`) — the prefix is infrastructure, not vault structure.

Never hand-concatenate the prefix; see [architecture/frontend](../architecture/frontend.md#the-single-url-choke-point-libbackendts).

## The Docker image (supported deployment)

`Dockerfile` is a two-stage build: stage 1 builds the Vite frontend (Node 24); stage 2 is the Python 3.14 runtime that copies `dist/` into `static/` and runs **uvicorn as the only process** on port 8000. No reverse proxy, same-origin, no rebuild on redeploy.

- Vault + cache live under a single `/data` volume (`VAULT_DIR=/data/vault`, `CACHE_DIR=/data/cache`) — one bind mount keeps both portable.
- `docker-entrypoint.sh` starts as **root only** to reconcile the app user's UID/GID (`-e UID=$(id -u) -e GID=$(id -g)`) and `chown` the data mounts, then `gosu`-drops to the unprivileged `app` user before exec'ing uvicorn. This is accepted by design — it makes bind-mount ownership line up without a rebuild.
- The index-seed override is read from `~/.mdshards/index.md` (i.e. `/app/.mdshards/index.md`) — bind-mount a file there to customize the auto-created `index.md`. It's a **fixed path, never an env var** (an env-configurable template path would be an arbitrary-file-read vector).

### The three deployment modes

The threat model is blunt (see [domain/concepts](../domain/concepts.md#no-auth-but-a-boundary)). Only mode 1 is supported:

1. **Single container, static + uvicorn (supported).** As above.
2. **Node front, backend hidden (your own risk).** `VITE_BACKEND_HOST=<url> npm run preview` — runtime proxy target, no rebuild.
3. **Static host with a baked backend URL (your own risk, worst).** `VITE_BACKEND_HOST=<url> npm run build` bakes the origin into the bundle. The saner variant is the routing trick — `deploy/nginx.conf` + compose is the verified example (note `$http_host`, not `$host`, so the port survives for the origin guard).

`deploy/` holds the mode-2/3 examples (`docker-compose.yml`, `docker-compose.preview.yml`, `nginx.conf`, `nginx.Dockerfile`, `preview.Dockerfile`).

## CI & release workflows (`.github/workflows/`)

- **`ci.yml`** — runs on push/PR: `backend` (ruff lint + pytest w/ coverage → Codecov), `frontend` (`tsc -b` typecheck + vitest coverage), `e2e` (builds the shipping image, runs Playwright across Chromium/Firefox/WebKit, always `down -v`), plus a Docker Hub description validation job. SonarCloud + Snyk also gate PRs.
- **`release.yml`** — triggers on a `v*` tag (or manual dispatch with a version). Publishes the multi-arch (`amd64`+`arm64`) single-container image to `wzaldivar/mdshards` with four tags: rolling `X`, `X.Y`, `latest`, and the immutable `X.Y.Z` (guarded against overwrite). Version must be plain `X.Y.Z`.
- **`demo-publish.yml`** — **manual only**; builds the `demo` branch → `wzaldivar/mdshards-demo:latest` (a separate Docker Hub repo).
- **`guard-demo-pr.yml`** — a required check that **fails any PR from `demo`/`demo/*` into `main`**.
- **`demo-description.yml`, `dockerhub-description.yml`** — sync the Docker Hub pages.

### Release procedure (as practiced)

1. Bump `frontend/package.json` + lockfile, commit `Release X.Y.Z: …`, PR into `main`.
2. After merge, push tag `vX.Y.Z` → `release.yml` publishes the versioned image.
3. **Fold to demo (one-way):** on `demo`, `git merge main`, push. The demo branch carries public-hardening divergence (read-only landing page, upload/asset endpoints removed, external images swapped for Lorem Picsum, path cap) that **must never reach main** — hence the guard. Never PR demo → main.
4. **Release demo:** manually dispatch `demo-publish.yml`.

See `docs/ci-setup.md` for the required secrets (`DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`) — until they exist the release job is a green no-op.
