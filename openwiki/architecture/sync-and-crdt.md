# Sync & CRDT layer

This is the core of mdshards. All of it lives in `backend/app/docs.py` (`DocumentManager`), `backend/app/ws.py` (the wire protocol), and `backend/app/watcher.py` (external writers). The client half is `frontend/src/lib/crdt.ts`.

**Design invariant:** the on-disk `.md` is canonical; the in-memory `Doc` exists only to mediate concurrent edits and is reconciled back to disk. CRDT is the sync substrate — Yjs on the client, `pycrdt` on the server, kept in lockstep on the wire format.

## In-memory document lifecycle

A `.md` is loaded into a `Doc` when the **first** client connects and stays resident while ≥1 client is attached (`DocumentManager.acquire`/`release`). When the last client disconnects, the doc **lingers for a grace period** (`grace_period_seconds`, default 30s; `config.py`) before a final flush + eviction (`_evict_after_grace` → `_teardown`), so reloads and brief network blips reconnect to the same in-memory state.

- `_load` seeds a `Doc` from disk (or restores it from the binary cache — see below), sets `last_disk_content`, registers a change observer, and starts the flush loop.
- `_key` canonicalizes aliases: `""` (vault root) and `"index"` both resolve to `<vault>/index.md` and share one `Doc`.

## The WebSocket protocol (`ws.py`)

Each client gets a task driving the y-protocol handshake (`SYNC_STEP1` / `SYNC_STEP2` / `SYNC_UPDATE`) plus awareness relay, using `pycrdt`'s `create_sync_message` / `handle_sync_message`. Two subtleties encoded here:

- **Server→client keepalive** (`_KEEPALIVE_SECONDS = 10`): y-websocket hard-closes a socket that received no server message for 30s (`messageReconnectTimeout`); an idle doc is exactly that silence. Client timers can't prevent it (Safari throttles unfocused tabs), but *incoming* messages reach throttled tabs, so the server pushes an empty-awareness no-op frame (`_KEEPALIVE_MSG`) every 10s.
- **Kick signals** (`KickSignal`, close codes `DOC_DELETED_CODE=4001` / `DOC_MOVED_CODE=4002`): how a delete/rename forcibly closes attached sockets. (Note: Safari/WebKit reports `1006` instead of the app code — current-tab outcomes are also driven from the initiating REST request, not only the WS close.)

## Persistence — the flush loop

Changes are persisted by a per-doc debounced background task (`_flush_loop`), coalescing a burst of edits into one write after `FLUSH_QUIET_SECONDS = 0.5`. `_flush` is **the single reconcile-and-write step** and is synchronous by design (pycrdt Docs are only touched on the loop thread). A failing flush is logged loudly and the loop stays alive to retry — never silently dropping writes.

Each flush also writes the **binary Yjs cache** at `$CACHE_DIR/<vault-hash>/<rel-path>.yjs` (default `~/.cache/mdshards/`, outside the vault so the vault stays strictly plain `.md`). The cache preserves CRDT item IDs across grace eviction and restart so reconnecting clients don't merge the same characters in twice. It's an optimization: a cache write failure degrades to a warning and never undoes the vault write.

## Conflict policy — one unified line-based 3-way merge

**Both** reconciliation directions funnel through `_flush`, so a single policy governs them instead of two paths racing to disagree:

- the debounced flush loop (memory → disk), and
- the watcher's `reconcile_external` (disk → memory), which adds only trigger plumbing + a self-write filter and then calls `_flush`.

On divergence (`disk_now != last_disk_content`), `_flush` runs `_three_way_merge(base=last_disk_content, ours=live doc, theirs=disk)` (`docs.py`):

- a region **only one side** changed → take that side (non-overlapping edits from both sides **combine losslessly**);
- both changed it **identically** → take once, no conflict;
- both changed it **differently** → **true conflict**: keep OURS in the merged text (the live doc wins, in memory and on disk) and write a Syncthing-style **`foo.sync-conflict-<timestamp>.md`** file capturing THEIRS.

The merged text is written back and adopted as the new `last_disk_content` (so a divergence never conflicts twice), and folded-in disk hunks replay as `Y.Text` splices — the **"ghost editor"** — so they fan out to connected clients via the normal `on_event` path. This is line-based (`_unchanged_line_map` uses `SequenceMatcher(autojunk=False)` over lines) and **has no similarity/"trustworthiness" ratio heuristic** — a big external rewrite with no competing local edit is just an update, not a fake conflict. (This is the current design as of Release 1.5.0, replacing an earlier 2-way ghost-merge that could silently drop a concurrent client edit; see the conflict-policy bullet in [`CLAUDE.md`](../CLAUDE.md).)

**Cold-open (`_load`) is deliberately NOT unified into this:** a within-grace cache restore keeps the cached doc and conflict-files any disk divergence rather than 3-way merging.

## External writers (`watcher.py`)

The use case is `mdshards vault <> Syncthing <> Obsidian vault` — another tool may overwrite a `.md` while a browser edits it. A `watchdog` observer over the vault root reconciles **only actively-loaded docs** (deliberately not idle notes, to avoid blob-cache churn; idle notes reconcile lazily on next open via `_load`). Observer events fire on watchdog's own thread and are dispatched onto the asyncio loop via `run_coroutine_threadsafe` (pycrdt Docs mutate only on the loop thread). Self-writes are filtered by comparing disk against `last_disk_content` — which also breaks the write → watcher-event → write loop.

## Disconnection semantics (a hard stop, not offline mode)

This is a network-convenience editor, **not** offline-first (see [domain/concepts](domain/concepts.md#no-offline-editing)):

- **Within the grace period**, a dropped socket is a blip — the client keeps editing optimistically and a quick reconnect resumes the *same* in-memory doc.
- **Past the grace period**, the frontend goes **read-only** with a notification (the read-only threshold reuses the grace period from `/api/config`).
- **On reconnect after that window, the browser's local `Y.Doc` is dismissed, not merged** — the client drops its doc and re-syncs server state from scratch. A disconnected client is never a first-class author. Do not add offline-merge machinery to the reconnect path.

## Where to start / what to watch

- The merge logic is `_three_way_merge` + `_merge_region` + `_apply_ghost_merge` in `docs.py`; tests are `backend/tests/test_docs.py` (flush/conflict/cache) and `test_watcher.py` (reconciliation + a real-observer end-to-end test).
- Anything touching persistence must keep `last_disk_content` accurate — it's both the merge base and the self-write filter.
- Keep the on-disk format strictly portable markdown; a round-trip through Obsidian/Syncthing must not corrupt anything.
- Client/server wire-format changes must move together (`crdt.ts` ⇄ `ws.py`).
