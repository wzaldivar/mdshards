# mdshards — OpenWiki quickstart

**mdshards** is a SilverBullet-inspired editor for a vault of plain markdown notes. A **FastAPI** server (Python 3.14) owns a directory of `.md` files on disk — **no database** — and exposes it to a **React 19 + TypeScript** SPA. Live editing is synced with **CRDT** (Yjs on the client, `pycrdt` on the server) over a WebSocket; everything else (uploads, listings, metadata) is plain REST. There is **no authentication** — it's meant to run in a trusted environment (a LAN server).

The design north star: **the filesystem is the source of truth and the client is thin and disposable.** See [domain/concepts](domain/concepts.md) for why that shapes almost every decision.

> The canonical, exhaustive architecture spec is the repo-root [`CLAUDE.md`](../CLAUDE.md) (load-bearing decisions you must not silently reverse) and the feature inventory is [`FEATURES.md`](../FEATURES.md). This wiki is a navigable summary that links into them.

## What it's for

Editing notes that live on a LAN server, in the browser, without SMB or a scripting platform — designed to coexist with an Obsidian + Syncthing setup writing the *same* vault (hence the external-writer reconciliation). Plain `.md` means the data survives any tool. (README: "Why mdshards".)

## Tech stack

| Layer | Tech | Entry point |
|---|---|---|
| Backend | FastAPI, `pycrdt`, `watchdog`, pydantic-settings | `backend/app/main.py` (`app.main:app`) |
| Frontend | React 19, Vite, `react-router` v7, CodeMirror 6, Yjs + `y-websocket` | `frontend/src/main.tsx` |
| Sync | y-websocket protocol over WS; `pycrdt` ⇄ Yjs | `backend/app/ws.py`, `frontend/src/lib/crdt.ts` |
| Toolchain | pinned via `.mise.toml` (Python 3.14 + Node 24 LTS) | `.mise.toml` |

## Dev quick-start

```bash
# Backend (from backend/) — needs VAULT_DIR
pip install -r backend/requirements-dev.txt
VAULT_DIR=../vault uvicorn app.main:app --reload

# Frontend (from frontend/) — proxies /api and /ws to 127.0.0.1:8000
npm install && npm run dev
```

`mise` auto-creates and activates a repo-root `.venv/`; never install packages globally. The only required setting is `VAULT_DIR`; see [operations/deployment](operations/deployment.md) for the rest.

## Sections

- **[architecture/backend](architecture/backend.md)** — FastAPI layering (thin routers over load-bearing service modules), the `/_mdshards` app-surface namespace, and the md-wins URL→path resolution rule.
- **[architecture/sync-and-crdt](architecture/sync-and-crdt.md)** — the heart of the system: in-memory document lifecycle, the WebSocket protocol, the grace period + blob cache, the unified 3-way conflict merge, and external-writer reconciliation.
- **[architecture/frontend](architecture/frontend.md)** — the SPA: routing, CodeMirror live-preview, the CRDT client, the single URL choke point, and the keyboard-first switchers.
- **[domain/concepts](domain/concepts.md)** — the "why": FS-is-king, no offline editing, no client database, no auth (but an origin boundary), vault portability.
- **[operations/deployment](operations/deployment.md)** — the three deployment modes, `BASE_URL` sub-path mounting, the Docker image, config/env vars, and the CI/release/demo workflows.
- **[testing](testing.md)** — the three test tiers (backend pytest, frontend vitest, e2e Playwright multi-engine) and their gotchas.

## Load-bearing principles at a glance

These are choices you can't recover from the code alone — preserve them unless explicitly told otherwise (full list in [`CLAUDE.md`](../CLAUDE.md)):

- **Server/disk is the source of truth.** CRDT state in memory exists only to mediate concurrent edits; it's reconciled back to disk. No client-side database (one narrow exception: small editor UI prefs in `localStorage`).
- **CRDT over WebSocket; everything else over REST.** Don't tunnel one through the other.
- **Only `.md` is editable.** Assets are read-only bytes, mutated only via upload/delete, never entering the CRDT layer.
- **Plain `.md` on disk, portable and relative.** No sidecar metadata, no host-absolute asset URLs (one out-of-vault exception: the binary Yjs cache).
- **A boundary despite no auth:** path-traversal is rejected (`vault.py`), and an origin guard (`security.py`) gates state-changing requests and WS upgrades.
