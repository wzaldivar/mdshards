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
- **Kick signals** (`KickSignal`, close codes `DOC_DELETED_CODE=4001` / `DOC_MOVED_CODE=4002`): how a delete/rename/conflict forcibly closes attached sockets. (Note: Safari/WebKit reports `1006` instead of the app code — current-tab outcomes are also driven from the initiating REST request, and from the `GET /api/moved` forward for cases the tab didn't initiate; see Conflict policy.)

## Persistence — the flush loop and the two reconcile directions

Changes are persisted by a per-doc debounced background task (`_flush_loop`), coalescing a burst of edits into one write after `FLUSH_QUIET_SECONDS = 0.5`. There are **two reconcile directions, coordinated by a per-doc `io_lock` so they are never in flight together:**

- **OUT** (`_flush_out`, memory → disk): the flush loop takes `io_lock` **blocking**. It first *drains* any pending external change with pseudo-INs (the IN step below, run without re-locking, repeated until the disk stops changing), then writes the "golden snapshot" to disk.
- **IN** (`reconcile_external` → `_reconcile_once`, disk → memory): the watcher takes `io_lock` as a **try-lock** — if held it returns immediately (OUT's drain absorbs the change) rather than queueing.

Both are synchronous once they hold the lock (pycrdt Docs are only touched on the loop thread). A failing flush is logged loudly and the loop stays alive to retry — never silently dropping writes.

**`golden_hash`** (sha256 of `last_disk_content`) is the O(1) change guard: on a watcher event, IN hashes disk and compares — equal means our own write or a no-op touch, skipped without diffing (the free self-write filter, and what breaks the write → event → write loop); on a flush, OUT compares `sha(memory)` and **skips the write syscall entirely** when memory already equals disk (zero write-amplification against Syncthing).

Each flush also writes the **binary Yjs cache** at `$CACHE_DIR/<vault-hash>/<rel-path>.yjs` (default `~/.cache/mdshards/`, outside the vault so the vault stays strictly plain `.md`). The cache preserves CRDT item IDs across grace eviction and restart so reconnecting clients don't merge the same characters in twice. It's an optimization: a cache write failure degrades to a warning and never undoes the vault write.

## Conflict policy — git-style 3-way, loud on a true conflict

IN reconciles via `_three_way_merge(base=last_disk_content, ours=live doc, theirs=disk)` (line-based, `SequenceMatcher(autojunk=False)` over lines):

- a region **only one side** changed → take that side (disjoint external + local edits **combine losslessly**);
- both changed it **identically** → take once, no conflict;
- both changed it **differently** → a git-style **conflict** (the disk hunk can't apply over the live edit).

A clean merge folds the external hunks into the live doc as `Y.Text` splices replayed **EOF→0** (reversed opcodes — the **"ghost editor"**, `_apply_ghost_merge`), fanning out to clients via `on_event`; the IN **never writes disk** (`last_disk_content` just tracks what disk holds now). A conflict is handled **loudly, not silently** (`_to_conflict`): write the live (web) doc to a distinctly-named **`foo.mdshards-conflict-<timestamp>.md`** file (distinct from Syncthing's own `*.sync-conflict-*`), drop the doc, and **kick every attached client to that file** (`DOC_MOVED_CODE`) — the main file **keeps the FS version** (we can't merge it without noise). Nobody's data is lost: theirs on the main file, ours in the conflict file. (User decision 2026-07-18, replacing the Release 1.5.0 unified-`_flush` 3-way that produced timing-dependent inconsistent merges + echo-write amplification against Syncthing; see the conflict-policy bullet in [`CLAUDE.md`](../CLAUDE.md).)

**Move/delete forward for lost close codes.** Every `kick` records a short-lived forward — move/conflict → the new doc-id, delete → `""` (root) — served by **`GET /api/moved/{doc_id}`** (`resolve.py`, `DocumentManager.forward_target`). Safari/WebKit reports our 4001/4002 close codes as a bare `1006` with no reason, so a WebKit tab queries this on an unexplained drop to still surface the explicit "follow" link (or navigate home) instead of a dead read-only banner.

**Cold-open (`_load`) keeps its own policy:** a within-grace cache restore keeps the cached doc and conflict-files any disk divergence rather than 3-way merging.

## External writers (`watcher.py`)

The use case is `mdshards vault <> Syncthing <> Obsidian vault` — another tool may overwrite a `.md` while a browser edits it. A `watchdog` observer over the vault root reconciles **only actively-loaded docs** (deliberately not idle notes, to avoid blob-cache churn; idle notes reconcile lazily on next open via `_load`). Observer events fire on watchdog's own thread and are dispatched onto the asyncio loop via `run_coroutine_threadsafe` (pycrdt Docs mutate only on the loop thread). Self-writes are filtered by the `golden_hash` of `last_disk_content` — which also breaks the write → watcher-event → write loop.

## Disconnection semantics (a hard stop, not offline mode)

This is a network-convenience editor, **not** offline-first (see [domain/concepts](domain/concepts.md#no-offline-editing)):

- **Within the grace period**, a dropped socket is a blip — the client keeps editing optimistically and a quick reconnect resumes the *same* in-memory doc.
- **Past the grace period**, the frontend goes **read-only** with a notification (the read-only threshold reuses the grace period from `/api/config`).
- **On reconnect after that window, the browser's local `Y.Doc` is dismissed, not merged** — the client drops its doc and re-syncs server state from scratch. A disconnected client is never a first-class author. Do not add offline-merge machinery to the reconnect path.

## Where to start / what to watch

- The two directions are `_flush_out` (OUT) and `reconcile_external`/`_reconcile_once` (IN), gated by `io_lock`; the merge logic is `_three_way_merge` + `_merge_region` + `_apply_ghost_merge`, and a true conflict goes through `_to_conflict` (+ `forward_target` for `GET /api/moved`). Tests: `backend/tests/test_docs.py` (flush/conflict/cache/forward) and `test_watcher.py` (both reconciliation directions, conflict-move, and a real-observer end-to-end test).
- Anything touching persistence must keep `last_disk_content` accurate — it's both the merge base and the self-write filter.
- Keep the on-disk format strictly portable markdown; a round-trip through Obsidian/Syncthing must not corrupt anything.
- Client/server wire-format changes must move together (`crdt.ts` ⇄ `ws.py`).
