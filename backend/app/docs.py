"""In-memory CRDT document lifecycle: load on first connect, persist on change,
linger for a grace period after the last client leaves, then evict.

The on-disk `.md` is the source of truth; `Doc` instances exist only to mediate
concurrent edits. See CLAUDE.md for the lifecycle and conflict-policy rules.
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import logging
import os
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pycrdt import Doc, Subscription, Text, create_update_message

from .files import read_md, write_bytes_atomic, write_md_atomic
from .vault import VaultPathError, assert_inside, resolve_md

logger = logging.getLogger("mdshards.docs")

FLUSH_QUIET_SECONDS = 0.5
TEXT_KEY = "content"

# Safety bound on the OUT drain loop: how many pseudo-INs to run absorbing a
# burst of external writes before flushing anyway. The expected workload is
# small discrete changes (Obsidian/Syncthing), which settle in ~1 pass; this is
# only a backstop against a continuously-rewriting external writer livelocking
# the flush while holding the io_lock.
_MAX_PSEUDO_IN = 64

# How long a move/conflict "forward" (old doc-id → new location) is queryable
# via GET /api/moved. It exists so a client whose WebSocket dropped without a
# usable close code — Safari/WebKit reports our app close codes as a bare 1006 —
# can still learn where its doc went and offer an explicit link. Long enough for
# a user to notice the drop and click; short enough to stay a tiny transient map.
_FORWARD_TTL_SECONDS = 300

# WebSocket close codes the manager emits when forcibly disconnecting clients.
# Defined here (rather than in ws.py) so DocumentManager can build the close
# signal without importing the WebSocket router module.
DOC_DELETED_CODE = 4001
DOC_MOVED_CODE = 4002


@dataclass(frozen=True)
class KickSignal:
    """Pushed into a subscriber queue to tell the WS writer to close. The code
    and reason are forwarded as the WebSocket close frame."""

    code: int
    reason: str = ""


@dataclass
class _DocState:
    doc: Doc
    disk_path: Path
    refcount: int = 0
    # A `KickSignal` value tells the WS writer to close with the given code/
    # reason — used when the file is deleted or moved out from under attached
    # clients.
    subscribers: set[asyncio.Queue[bytes | KickSignal]] = field(default_factory=set)
    eviction_task: asyncio.Task | None = None
    flush_task: asyncio.Task | None = None
    flush_pending: asyncio.Event = field(default_factory=asyncio.Event)
    # The 3-way merge base: the last content where doc and disk agreed. Tracks
    # what is currently on disk (set by every IN and every OUT).
    last_disk_content: str = ""
    # sha256(last_disk_content). The O(1) change/self-write guard: on a watcher
    # event we hash disk and compare — equal means our own write or a no-op
    # touch, skip without diffing; on a flush, equal means memory already matches
    # disk, skip the write syscall entirely.
    golden_hash: str = ""
    observer: Subscription | None = None
    # Coordinates the two reconcile directions for THIS doc: OUT (flush loop,
    # memory→disk) takes it BLOCKING — it waits for any in-flight IN, then owns
    # the doc for its whole drain-then-flush. IN (watcher, disk→memory) takes it
    # as a TRY-lock — if held it returns immediately rather than queueing, since
    # OUT's pseudo-IN loop will absorb the change anyway.
    io_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class DocumentManager:
    """Owns the in-memory `Doc` for each markdown path that has at least one
    attached client, plus the grace-period and flush bookkeeping."""

    def __init__(
        self,
        vault_dir: Path,
        grace_period_seconds: float,
        cache_dir: Path,
    ) -> None:
        self._vault_dir = vault_dir
        self._grace = grace_period_seconds
        # One bucket per vault, hashed so two vaults at different paths can't
        # collide on cache files when their internal layouts overlap.
        vault_hash = hashlib.sha256(str(vault_dir.resolve()).encode()).hexdigest()[:16]
        self._cache_root = cache_dir / vault_hash
        self._docs: dict[str, _DocState] = {}
        self._lock = asyncio.Lock()
        # Short-lived "this doc moved/conflicted to here" records, keyed by the
        # resolved path (the same key as `_docs`), value = (target doc-id,
        # monotonic expiry). Served by GET /api/moved — see `_FORWARD_TTL_SECONDS`.
        self._forwards: dict[str, tuple[str, float]] = {}

    def _key(self, doc_id: str) -> str:
        """Canonical key for a doc: the resolved on-disk path. Ensures aliases
        like '' and 'index' (both → <vault>/index.md) share a single Doc."""
        return str(resolve_md(doc_id, self._vault_dir))

    def _cache_path(self, disk_path: Path) -> Path:
        """Where the binary Yjs state for `disk_path` lives. Mirrors the vault's
        relative layout under the per-vault cache root, with a `.yjs` suffix.
        Asserts the resulting path stays inside the per-vault cache root —
        defense-in-depth so a malformed `disk_path` can't redirect cache writes
        somewhere else on disk."""
        rel = disk_path.resolve().relative_to(self._vault_dir.resolve())
        candidate = self._cache_root / f"{rel}.yjs"
        assert_inside(candidate, self._cache_root)
        return candidate

    async def acquire(self, doc_id: str) -> _DocState:
        key = self._key(doc_id)
        async with self._lock:
            state = self._docs.get(key)
            if state is None:
                state = self._load(doc_id)
                self._docs[key] = state
            if state.eviction_task is not None:
                state.eviction_task.cancel()
                state.eviction_task = None
            state.refcount += 1
            return state

    async def release(self, doc_id: str) -> None:
        key = self._key(doc_id)
        async with self._lock:
            state = self._docs.get(key)
            if state is None:
                return
            state.refcount -= 1
            if state.refcount <= 0:
                state.refcount = 0
                state.eviction_task = asyncio.create_task(self._evict_after_grace(key))

    def _load(self, doc_id: str) -> _DocState:
        disk_path = resolve_md(doc_id, self._vault_dir)
        cache_path = self._cache_path(disk_path)
        disk_content = read_md(disk_path, self._vault_dir) if disk_path.exists() else ""

        doc = Doc()
        authoritative: str
        cached_update: bytes | None = None
        if cache_path.exists():
            try:
                cached_update = cache_path.read_bytes()
            except OSError:
                # Unreadable cache (mount permissions) — the cache is an
                # optimization, so degrade to a fresh disk load instead of
                # refusing to open the note at all.
                logger.warning(
                    "CRDT cache unreadable at %s — loading %s fresh from disk",
                    cache_path,
                    disk_path,
                    exc_info=True,
                )
        if cached_update is not None:
            # Restore the prior CRDT state with all its original item IDs so
            # clients still holding a Y.Doc from before can sync against the
            # SAME items rather than getting "the same text again" as fresh
            # inserts (which would duplicate on merge).
            doc.apply_update(cached_update)
            authoritative = str(doc.get(TEXT_KEY, type=Text))
            if disk_path.exists() and disk_content != authoritative:
                # External writer touched the file while the cache was the
                # source of truth — preserve their changes as a conflict file,
                # but keep the live Doc unchanged.
                self._write_conflict_file(disk_path, disk_content)
        else:
            # Fresh doc: seed the root Text from disk in place. No local — the
            # point is the side-effecting mutation of the shared type, not a
            # value we reuse (an intermediate `text` var reads as a dead store).
            if disk_content:
                doc.get(TEXT_KEY, type=Text).insert(0, disk_content)
            authoritative = disk_content

        state = _DocState(
            doc=doc,
            disk_path=disk_path,
            last_disk_content=authoritative,
            golden_hash=self._sha(authoritative),
        )

        def on_event(event) -> None:
            state.flush_pending.set()
            msg = create_update_message(event.update)
            for q in state.subscribers:
                q.put_nowait(msg)

        state.observer = doc.observe(on_event)
        state.flush_task = asyncio.create_task(self._flush_loop(state))
        return state

    async def _flush_loop(self, state: _DocState) -> None:
        # Cancelled at teardown; CancelledError propagates on its own (no
        # cleanup needed). A failing flush (unwritable vault mount, disk
        # full…) must NOT kill this task: an unretrieved task exception is
        # never even logged while the task object stays referenced, which
        # turns a permissions problem into silent, total write loss behind a
        # healthy-looking editor. Log it loudly and keep the loop alive — the
        # next edit re-arms flush_pending and retries.
        while True:
            await state.flush_pending.wait()
            while state.flush_pending.is_set():
                state.flush_pending.clear()
                await asyncio.sleep(FLUSH_QUIET_SECONDS)
            try:
                # OUT waits (blocking) for the io_lock: an IN in flight finishes
                # first. Once held, watcher INs skip (they see it locked) and OUT
                # owns the doc for the whole drain-then-flush below.
                async with state.io_lock:
                    moved = await self._flush_out(state)
                if moved:
                    return  # doc was moved to a conflict file; this loop is done
            except Exception:
                logger.exception(
                    "flush of %s FAILED — the vault did not receive this "
                    "change; will retry on the next edit. Check mount "
                    "ownership/permissions (UID/GID envs).",
                    state.disk_path,
                )

    async def _flush_out(self, state: _DocState) -> bool:
        """OUT direction (memory→disk), run under `state.io_lock`. First drain
        every pending external change with pseudo-INs — an IN run without
        re-locking (we already hold the lock), repeated until the disk stops
        changing, re-snapshotting each pass — then write the golden snapshot.
        Returns True if a pseudo-IN hit a conflict and moved the doc to a
        conflict file: the caller must stop, the doc is gone."""
        for _ in range(_MAX_PSEUDO_IN):
            result = self._reconcile_once(state)
            if result == "conflict":
                await self._to_conflict(state, await_flush=False)
                return True
            if result == "noop":
                break  # disk quiescent — nothing more incoming
            # "merged": folded an external change in; loop to catch any more.
        # Golden-snapshot flush. Write only when memory actually differs from
        # disk — the O(1) hash guard. A pure IN leaves memory == disk, so it
        # costs zero write syscalls and never wakes Syncthing (the old
        # write-amplification that made mdshards race its own syncs).
        content = str(state.doc.get(TEXT_KEY, type=Text))
        if self._sha(content) != state.golden_hash:
            write_md_atomic(state.disk_path, content, self._vault_dir)
            state.last_disk_content = content
            state.golden_hash = self._sha(content)
        self._write_cache(state)
        return False

    def _reconcile_once(self, state: _DocState) -> str:
        """One IN pass (disk→memory), run under `state.io_lock` — directly by the
        watcher IN, or as a pseudo-IN inside `_flush_out`. Returns one of:
          "noop"     — disk unchanged since our last golden snapshot;
          "merged"   — external hunks folded into the live doc (EOF→0 patch);
          "conflict" — a disk hunk lands on a region the live doc also changed,
                       git-style unapplyable — the caller moves the doc to a
                       conflict file (we can't merge it without noise)."""
        if not state.disk_path.exists():
            return "noop"  # vanished — the delete/rename path owns removal
        try:
            disk = read_md(state.disk_path, self._vault_dir)
        except OSError, VaultPathError:
            return "noop"
        # O(1) golden-hash guard: identical bytes mean our own write or a no-op
        # touch — the free self-write filter, and what stops the write→event→
        # write loop.
        if self._sha(disk) == state.golden_hash:
            return "noop"
        current = str(state.doc.get(TEXT_KEY, type=Text))
        merged, conflict = self._three_way_merge(state.last_disk_content, current, disk)
        if conflict:
            return "conflict"
        if merged != current:
            # Fold the external hunks in as Y.Text splices (reversed, EOF→0) so
            # they fan out to clients through on_event — as if a ghost typed it.
            self._apply_ghost_merge(state, current, merged)
        # The base tracks what is actually on disk now (we did not change disk
        # here). If `merged` kept local edits the disk lacks, memory is ahead and
        # the golden flush persists it on the next OUT.
        state.last_disk_content = disk
        state.golden_hash = self._sha(disk)
        return "merged"

    async def reconcile_external(self, disk_path: Path) -> None:
        """IN direction (disk→memory), triggered by the watcher. Fold an external
        on-disk change to an actively-loaded `.md` into its in-memory Doc via a
        git-style line-based 3-way merge: disjoint hunks combine and are replayed
        as `Y.Text` splices (EOF→0 order) — the "ghost editor" — fanning out to
        clients through `on_event`. A hunk that lands on a region the live doc
        also changed is a true conflict: move the web side to a conflict file and
        kick its clients there, leaving the FS version canonical (we can't merge
        that without noise).

        Try-lock, never blocks: a held io_lock means OUT (or another IN) is
        already reconciling and will absorb this change, so queueing would only
        duplicate work. No-op for idle notes (reconciled lazily on next open) and
        for a vanished file."""
        key = str(disk_path.resolve())
        async with self._lock:
            state = self._docs.get(key)
        if state is None:
            return
        if state.io_lock.locked():
            return
        async with state.io_lock:
            if self._reconcile_once(state) == "conflict":
                await self._to_conflict(state, await_flush=True)

    async def _to_conflict(self, state: _DocState, *, await_flush: bool) -> None:
        """Handle an irreconcilable IN: write the live (web) doc to a conflict
        file, drop the doc, and kick every attached client to that file so they
        can recover their side. The main file keeps the FS version — we do NOT
        write it. `await_flush=False` when called from inside the flush task
        itself (a task can't cancel/await itself; the loop returns instead)."""
        conflict_path = self._write_conflict_file(
            state.disk_path, str(state.doc.get(TEXT_KEY, type=Text))
        )
        conflict_id = str(
            conflict_path.resolve().relative_to(self._vault_dir.resolve()).with_suffix("")
        )
        key = str(state.disk_path.resolve())
        # Record the forward so a client that dropped without a usable close
        # code (Safari) can still discover the conflict file via GET /api/moved.
        self._record_forward(key, conflict_id)
        async with self._lock:
            self._docs.pop(key, None)
        if state.eviction_task is not None:
            state.eviction_task.cancel()
            with suppress(asyncio.CancelledError):
                await state.eviction_task
        if await_flush and state.flush_task is not None:
            state.flush_task.cancel()
            with suppress(asyncio.CancelledError):
                await state.flush_task
        signal = KickSignal(code=DOC_MOVED_CODE, reason=conflict_id)
        for q in state.subscribers:
            q.put_nowait(signal)

    def _write_cache(self, state: _DocState) -> None:
        # Persist the binary CRDT state so the next load rehydrates items with
        # their original IDs. The cache is an optimization, never load-bearing —
        # a failure (unwritable CACHE_DIR mount) must not undo the vault write or
        # poison the flush loop, so it degrades to a warning.
        try:
            write_bytes_atomic(
                self._cache_path(state.disk_path),
                state.doc.get_update(b"\x00"),
                self._cache_root,
            )
        except OSError:
            logger.warning(
                "CRDT cache write failed under %s — the vault write "
                "succeeded; reconnects fall back to fresh loads. Check the "
                "cache mount's ownership/permissions.",
                self._cache_root,
                exc_info=True,
            )

    @staticmethod
    def _sha(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _three_way_merge(base: str, ours: str, theirs: str) -> tuple[str, bool]:
        """Line-based 3-way merge against the common `base`. Returns (merged,
        conflict). A region only one side changed is taken from that side —
        disjoint edits combine; a region both sides changed differently is a
        git-style conflict (the disk hunk can't apply over the live edit) and
        raises the flag. Lines are split keepends so the join round-trips
        byte-for-byte, including a missing trailing newline."""
        base_l = base.splitlines(keepends=True)
        ours_l = ours.splitlines(keepends=True)
        theirs_l = theirs.splitlines(keepends=True)
        o_map = DocumentManager._unchanged_line_map(base_l, ours_l)
        t_map = DocumentManager._unchanged_line_map(base_l, theirs_l)
        # Sync points: base lines surviving UNCHANGED into both sides partition
        # the buffers into independently-mergeable regions.
        sync = [i for i in range(len(base_l)) if i in o_map and i in t_map]
        out: list[str] = []
        conflict = False
        bi = oi = ti = 0
        for i in (*sync, None):
            if i is None:  # trailing region after the last sync point
                b_end, o_end, t_end = len(base_l), len(ours_l), len(theirs_l)
            else:
                b_end, o_end, t_end = i, o_map[i], t_map[i]
            region, c = DocumentManager._merge_region(
                base_l[bi:b_end], ours_l[oi:o_end], theirs_l[ti:t_end]
            )
            out.extend(region)
            conflict = conflict or c
            if i is not None:
                out.append(base_l[i])  # the synchronized (identical) line
                bi, oi, ti = i + 1, o_map[i] + 1, t_map[i] + 1
        return "".join(out), conflict

    @staticmethod
    def _unchanged_line_map(base_l: list[str], other_l: list[str]) -> dict[int, int]:
        """base-line-index → other-line-index for every base line unchanged in
        `other`. `autojunk=False` — the heuristic misbehaves on large text."""
        sm = difflib.SequenceMatcher(a=base_l, b=other_l, autojunk=False)
        mapping: dict[int, int] = {}
        for i, j, n in sm.get_matching_blocks():
            for k in range(n):
                mapping[i + k] = j + k
        return mapping

    @staticmethod
    def _merge_region(
        base_c: list[str], ours_c: list[str], theirs_c: list[str]
    ) -> tuple[list[str], bool]:
        """Resolve one region between two sync points. Returns (lines, conflict)."""
        if ours_c == base_c:
            return theirs_c, False  # only THEIRS changed here
        if theirs_c == base_c:
            return ours_c, False  # only OURS changed here
        if ours_c == theirs_c:
            return ours_c, False  # both made the identical change
        return ours_c, True  # both changed differently → git-style conflict

    @staticmethod
    def _apply_ghost_merge(state: _DocState, current: str, target: str) -> None:
        """Transform the live `Y.Text` from `current` into `target` by replaying
        `SequenceMatcher` opcodes as splices in one transaction, in reverse
        (EOF→0) so each edit's indices stay valid — a splice only shifts
        positions at or after it, and later opcodes hold higher indices."""
        text = state.doc.get(TEXT_KEY, type=Text)
        opcodes = difflib.SequenceMatcher(a=current, b=target, autojunk=False).get_opcodes()
        with state.doc.transaction():
            for tag, i1, i2, j1, j2 in reversed(opcodes):
                if tag == "equal":
                    continue
                if tag in ("replace", "delete"):
                    del text[i1:i2]
                if tag in ("replace", "insert"):
                    text.insert(i1, target[j1:j2])

    async def rename(self, src_doc_id: str, dst_doc_id: str) -> None:
        """Kick everyone attached to `src` (so they stop editing into a Doc
        whose underlying file is about to move) and move the binary cache to
        `dst` so subsequent acquires preserve the CRDT item IDs. Clients see
        the close code `DOC_MOVED_CODE` and `reason = dst_doc_id`, which the
        frontend uses to offer a "follow" link to the new location (or, on
        Safari where the close code is lost, learns it from GET /api/moved —
        `kick` records that forward)."""
        await self.kick(src_doc_id, code=DOC_MOVED_CODE, reason=dst_doc_id)
        try:
            src_disk = resolve_md(src_doc_id, self._vault_dir)
            dst_disk = resolve_md(dst_doc_id, self._vault_dir)
        except Exception:
            return
        src_cache = self._cache_path(src_disk)
        if not src_cache.exists():
            return
        dst_cache = self._cache_path(dst_disk)
        dst_cache.parent.mkdir(parents=True, exist_ok=True)
        # `_cache_path` already asserts containment, but the mkdir above could
        # in principle race a symlink into the dst-parent chain; re-check.
        assert_inside(src_cache, self._cache_root)
        assert_inside(dst_cache, self._cache_root)
        os.replace(src_cache, dst_cache)
        # Empty cache subdirs left behind get pruned too — same invariant as
        # the vault's empty-dir rule, applied to the per-vault cache root.
        parent = src_cache.parent
        root = self._cache_root.resolve()
        while parent != root and parent.is_relative_to(root):
            if not parent.exists() or any(parent.iterdir()):
                break
            parent.rmdir()
            parent = parent.parent

    async def kick(
        self,
        doc_id: str,
        *,
        code: int = DOC_DELETED_CODE,
        reason: str = "deleted",
    ) -> None:
        """Drop the in-memory state for `doc_id` and signal every subscriber to
        close its WebSocket with the given code/reason. Used when the underlying
        `.md` is being deleted or moved — we don't want a connected editor to
        keep typing into a Doc that will resurrect the file on its next flush.
        Does NOT write to disk."""
        key = self._key(doc_id)
        # Record a forward so a client that dropped without a usable close code
        # (Safari reports our 4001/4002 as a bare 1006) can still recover via
        # GET /api/moved: a move points at the new doc-id; a delete points at
        # root ("" → the client navigates home, mirroring the DOC_DELETED path).
        self._record_forward(key, reason if code == DOC_MOVED_CODE else "")
        async with self._lock:
            state = self._docs.pop(key, None)
        if state is None:
            return
        if state.eviction_task is not None:
            state.eviction_task.cancel()
            with suppress(asyncio.CancelledError):
                await state.eviction_task
        if state.flush_task is not None:
            state.flush_task.cancel()
            with suppress(asyncio.CancelledError):
                await state.flush_task
        signal = KickSignal(code=code, reason=reason)
        for q in state.subscribers:
            q.put_nowait(signal)

    def _record_forward(self, key: str, target: str) -> None:
        """Remember that the doc at `key` (a resolved path) moved/conflicted to
        `target` (a doc-id), so `forward_target` can hand a dropped client an
        explicit link to the new location. Opportunistically prunes expired
        entries so the map stays tiny."""
        now = time.monotonic()
        self._forwards = {k: v for k, v in self._forwards.items() if v[1] > now}
        self._forwards[key] = (target, now + _FORWARD_TTL_SECONDS)

    def forward_target(self, doc_id: str) -> str | None:
        """The move/conflict destination recorded for `doc_id`, if still within
        its TTL — else None. Backs GET /api/moved: a client whose WebSocket
        dropped without a usable close code (Safari) queries this to learn where
        its doc went instead of being stranded on a dead read-only banner."""
        try:
            key = self._key(doc_id)
        except Exception:
            return None
        entry = self._forwards.get(key)
        if entry is None:
            return None
        target, expiry = entry
        if time.monotonic() > expiry:
            self._forwards.pop(key, None)
            return None
        return target

    def purge(self, doc_id: str) -> None:
        """Clear the on-disk cache for `doc_id`. Call when the .md is deleted
        so a future note at the same path doesn't resurrect stale CRDT state.
        Empty parent directories under the per-vault cache root are pruned."""
        try:
            disk_path = resolve_md(doc_id, self._vault_dir)
        except Exception:
            return
        self._unlink_cache(self._cache_path(disk_path))

    def prune_orphaned_cache(self) -> int:
        """Drop cache files whose corresponding `.md` is no longer in the vault.
        Without this, files deleted while the server is down would resurrect
        their CRDT state on next acquire. Returns the number of files removed."""
        if not self._cache_root.exists():
            return 0
        vault_root = self._vault_dir.resolve()
        removed = 0
        for cache_file in self._cache_root.rglob("*.yjs"):
            # `<vault-hash>/foo/bar.md.yjs` → vault-relative `foo/bar.md`
            md_rel = cache_file.relative_to(self._cache_root).with_suffix("")
            md_path = vault_root / md_rel
            if not md_path.exists():
                self._unlink_cache(cache_file)
                removed += 1
        return removed

    def _unlink_cache(self, cache_path: Path) -> None:
        """Delete `cache_path` and prune empty parent dirs up to the per-vault
        cache root. No-op if the file doesn't exist. Asserts containment before
        deleting so a malformed `cache_path` can't unlink anything outside the
        per-vault cache root."""
        assert_inside(cache_path, self._cache_root)
        if cache_path.exists():
            cache_path.unlink()
        parent = cache_path.parent
        root = self._cache_root.resolve()
        while parent != root and parent.is_relative_to(root):
            if not parent.exists() or any(parent.iterdir()):
                break
            parent.rmdir()
            parent = parent.parent

    def _write_conflict_file(self, original: Path, diverged_content: str) -> Path:
        # Named distinctly from Syncthing's own `*.sync-conflict-*` so the two
        # never get confused (or caught by each other's ignore patterns) — an
        # mdshards conflict is ours, a sync-conflict is Syncthing's.
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        conflict = original.with_name(f"{original.stem}.mdshards-conflict-{ts}.md")
        write_md_atomic(conflict, diverged_content, self._vault_dir)
        return conflict

    async def _evict_after_grace(self, key: str) -> None:
        # A reconnect within the grace window cancels this task (see
        # `acquire`/`kick`). Let the CancelledError propagate — swallowing it
        # would mark the task "completed" and mislead any awaiter; the cancel
        # already means "don't evict," so there's nothing to clean up.
        await asyncio.sleep(self._grace)
        async with self._lock:
            state = self._docs.pop(key, None)
        if state is not None:
            await self._teardown(state)

    async def _teardown(self, state: _DocState) -> None:
        if state.flush_task is not None:
            state.flush_task.cancel()
            with suppress(asyncio.CancelledError):
                await state.flush_task
        try:
            async with state.io_lock:
                await self._flush_out(state)
        except Exception:
            # The final flush is best-effort: raising here would abort
            # eviction (leaking the doc) or cut a shutdown loop short,
            # dropping OTHER docs' final flushes with it.
            logger.exception("final flush of %s failed at teardown", state.disk_path)

    async def shutdown(self) -> None:
        async with self._lock:
            items = list(self._docs.items())
            self._docs.clear()
        for _, state in items:
            if state.eviction_task is not None:
                state.eviction_task.cancel()
                with suppress(asyncio.CancelledError):
                    await state.eviction_task
            await self._teardown(state)
