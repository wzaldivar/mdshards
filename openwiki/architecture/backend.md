# Backend architecture

FastAPI app under `backend/app/`, entry point `app.main:app`. The guiding shape: **routers are thin HTTP adapters; the load-bearing logic lives in top-level service modules** that the routers (and the CRDT layer) delegate to.

## App assembly (`main.py`)

`create_app()` builds the `FastAPI` instance and, critically, **installs `OriginGuard` as the outermost middleware** before mounting routers (`main.py::create_app`). The lifespan handler (`main.py::lifespan`) wires the runtime:

1. `settings.vault_dir.mkdir(...)` + `ensure_index_exists(...)` — materialize the vault and its `index.md`.
2. `DocumentManager(...)` on `app.state` — owns all in-memory CRDT docs.
3. `prune_orphaned_cache()` — drop `.yjs` cache entries for files deleted while offline.
4. `VaultWatcher(...).start(loop)` — stage-2 external-writer reconciliation ([sync-and-crdt](sync-and-crdt.md)).

## The `/_mdshards` app-surface namespace

Every mdshards-owned URL — REST API, WebSocket, the Vite bundle, the favicon — lives under the single reserved segment **`/_mdshards`**, so the **entire top-level namespace belongs to the vault** (a note or folder may be named `assets`, `api`, `ws`, anything). Routers carry their own `/api` or `/ws` segment and are mounted with `prefix=APP_PREFIX`, yielding `/_mdshards/api/...` and `/_mdshards/ws/...` (`main.py::create_app`). Only the catch-all `pages` router stays at the root.

The one cost: a vault path whose **first segment** is `_mdshards` is rejected loudly (`VaultPathError`) in `vault.py::_validate`, mirrored on the frontend in `paths.ts::validateVaultPath`. The constant lives in three lockstep places: `APP_PREFIX` (`security.py`), `_RESERVED_SEGMENT` (`vault.py`), and `APP_PREFIX` (`frontend/src/lib/backend.ts`).

> Throughout the docs, bare `/api/...` and `/ws/...` name the *logical* endpoint; the wire path carries the `/_mdshards` prefix (and any `BASE_URL` sub-path in front of it).

## Service modules (the load-bearing core)

| Module | Responsibility |
|---|---|
| `vault.py` | URL → filesystem path resolution and `assert_inside` — the **path-traversal boundary** (`VaultPathError`). Rejects `..`, absolute paths, null bytes, backslashes, out-of-vault symlinks, and the reserved `_mdshards` first segment. |
| `files.py` | Vault file read/write/rename/delete primitives, shared by the CRDT layer and the `files` router. Also `resolve_index_template` and `ensure_index_exists`. |
| `tree.py` | `build_tree()` — the vault walker backing the `tree` router. |
| `security.py` | `OriginGuard` middleware (see below). |
| `watcher.py` | `VaultWatcher`, the `watchdog` observer that drives external-writer reconciliation. |
| `docs.py` | `DocumentManager` — CRDT document lifecycle, persistence, conflict merge. The subject of [sync-and-crdt](sync-and-crdt.md). |

## Routers (`app/routers/`) — thin adapters

- `resolve.py` — backs `GET /api/resolve/{path}`; the md-wins / asset-fallback disambiguator.
- `pages.py` — catch-all returning the SPA shell or a 404 based on `Sec-Fetch-Dest` (document → shell; sub-resource → 404). Also `_prefix_shell` for `BASE_URL` sub-path rewriting.
- `files.py` — REST for markdown notes (upload-as-md, metadata, rename, delete); **mutations route through the CRDT layer**.
- `assets.py` — REST for non-`.md` bytes (upload/serve/delete; `GET /api/embed` resolves wikilink image targets). **Bypasses CRDT entirely.**
- `tree.py` — vault listing for the quick-switcher / pickers.
- `config.py` — `/api/config`; surfaces `homePath` (the React Router basename, derived from `BASE_URL`).

## URL → vault path mapping (md-wins resolution)

The backend disambiguates by **file existence, not URL pattern** (`resolve.py`). For URL `/X`:

1. `<vault>/X.md` exists → markdown note, doc-id `X`, `/X` is canonical.
2. Else if `X` ends in `.md`, recurse on `X` with `.md` stripped (the literal file `<vault>/X` is itself a note; canonical URL drops the `.md`).
3. Else try `<vault>/X` as an asset (extension required) → serve bytes.
4. Else → missing → serve the SPA shell so React renders its own NotFound view.

Consequences: **`.md` always wins** (`foo.jpg.md` shadows `foo.jpg` at `/foo.jpg`); paths are **case-sensitive**; **spaces are allowed** (stored literally, percent-encoded only at the URL boundary via `paths.ts::encodePathToUrl`); **URLs address files, never directories** (no `/foo/` listing route). The one exception: **`/` maps to `<vault>/index.md`**, auto-materialized from a template on first access.

File auto-creation is limited to exactly two paths: `index.md` on first access, and the frontend quick-switcher's explicit confirm-to-create. Nothing else creates files.

## The origin boundary (`security.py`)

No auth does **not** mean no CSRF/WS-hijack defense. `OriginGuard` gates by browser-set headers on the `BASE_URL`-stripped route path (which still carries `/_mdshards`):

- `/_mdshards/api/*` requires a browser fingerprint: `Sec-Fetch-Site ∈ {same-origin, same-site, none}` when present; else `Origin`/`Referer` matching the request's own `Host` (the plain-HTTP LAN fallback, where browsers send no Fetch Metadata).
- `/_mdshards/ws/*` requires `Origin` (browsers omit `Sec-Fetch-*` on the WS handshake but always send `Origin`).
- Static/asset/direct-nav paths keep a looser gate: safe methods (`GET`/`HEAD`/`OPTIONS`) always pass; only state-changing methods check origin.

This is **casual-bypass/CSRF defense, not authentication** — the trusted origin is the request's own `Host`, not a configured value. See [domain/concepts](domain/concepts.md#no-auth-but-a-boundary).

## Where to start / what to watch

- Changing routing or the reserved namespace touches `main.py`, `security.py::APP_PREFIX`, `vault.py::_RESERVED_SEGMENT`, and `frontend/src/lib/backend.ts` **together** — they must stay in lockstep.
- Any new mutation of a `.md` must go **through the CRDT layer** (`DocumentManager`), not a raw file write — see the conventions in [`CLAUDE.md`](../CLAUDE.md).
- Path-safety changes belong in `vault.py::_validate`; the tests are `backend/tests/test_vault.py` and `test_security.py`.
