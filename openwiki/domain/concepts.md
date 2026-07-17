# Domain concepts & load-bearing decisions

This page captures the *why* — the product philosophy and the deliberate constraints that shape the code. These are choices a reader can't recover from the code alone; the exhaustive list with full rationale is in [`CLAUDE.md`](../CLAUDE.md) ("Load-bearing architectural decisions"). **Preserve them unless the user explicitly says otherwise.**

## FS-is-king (and why not SilverBullet)

mdshards replaces a Syncthing + SilverBullet setup over an Obsidian vault. The author used SilverBullet but rejected it for: fighting the "filesystem is king" model, a Lua scripting platform he didn't need, and (the trigger) recent changes forcing TLS to deploy on a LAN. The **north star**: keep the filesystem the source of truth and the client thin and disposable. mdshards keeps the part that mattered — browser-based shared editing of plain files — and drops the platform.

Concretely: the on-disk `.md` files are canonical; in-memory CRDT state exists only to mediate concurrent edits and is reconciled back to disk ([sync-and-crdt](../architecture/sync-and-crdt.md)).

## No client-side database {#no-client-database}

The deliberate departure from SilverBullet: **no IndexedDB / SQLite-in-browser / PouchDB** on the frontend. The client holds the current CRDT doc in memory and nothing more. The one narrow exception is small editor UI preferences (vim mode, line numbers, typewriter scrolling) in `localStorage` under `mdshards:*` keys — losing them only reverts the editor to defaults. This category must **not** grow into caching note content, the tree, or any vault-derived data.

## No offline editing {#no-offline-editing}

This is a **network-convenience editor** for a vault someone also edits in Obsidian — not an offline-first or durable-authorship tool. A dropped socket within the grace period is a blip; past it, the client goes read-only, and on late reconnect its local `Y.Doc` is **dismissed, not merged** (server/disk wins). A disconnected client is never treated as a first-class author. This is the expected "offline dinosaur" wall, not a bug — do not engineer around it.

## No auth, but a boundary {#no-auth-but-a-boundary}

There is **no authentication or access control** — mdshards is meant for a trusted environment. The blunt threat model: running it is like exposing a VS Code instance to the world over your filesystem. But no-auth does **not** mean no boundary:

- **Path traversal is rejected** before any disk access (`vault.py` — the vault dir is the boundary).
- **An origin guard** (`security.py::OriginGuard`) defends against CSRF / WS-hijacking by gating state-changing requests and WS upgrades on browser-set headers. It is casual-bypass defense, **not** cryptographic authentication.

Do not add login flows, sessions, JWT/cookie middleware, or per-document ACLs unless explicitly asked. There is also **no read-only / safe-to-browse mode** and none is planned — no viewer-only mode, share links, or per-note visibility.

## Vault portability {#portability}

The vault is portable: asset references inside `.md` (images, links, embeds) use **vault-relative paths** that resolve when the vault is copied or edited with any other markdown tool. No host-absolute URLs for in-vault assets, no app-internal schemes — what the editor writes is what lands on disk. Plain `.md` on disk means **no sidecar metadata, no front-matter index, no DB shadow copies inside the vault**. The single out-of-vault exception is the binary Yjs cache.

Markdown follows **strict CommonMark**; the only sanctioned deviations are `[[wikilinks]]` and their `![[image]]` embed form (vault-rooted targets). See [`FEATURES.md`](../FEATURES.md).

## Only `.md` is editable

CRDT sync, in-memory documents, and live collaboration apply **exclusively** to markdown. Non-`.md` assets are read-only over their URL, mutated only via upload/delete endpoints, and never enter the CRDT layer. Do not generalize the editor or sync code to other formats without an explicit design discussion.

## md-wins routing & the vault namespace

URL→path resolution disambiguates by file existence, and **`.md` always wins** (`foo.jpg.md` shadows `foo.jpg`). The entire top-level URL namespace belongs to the vault because the app hides under `/_mdshards` — so a note can be named `assets`, `api`, `ws`. The mechanics are in [architecture/backend](../architecture/backend.md#url--vault-path-mapping-md-wins-resolution).
