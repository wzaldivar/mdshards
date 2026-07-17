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
    last_disk_content: str = ""
    observer: Subscription | None = None


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

        state = _DocState(doc=doc, disk_path=disk_path, last_disk_content=authoritative)

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
                self._flush(state)
            except Exception:
                logger.exception(
                    "flush of %s FAILED — the vault did not receive this "
                    "change; will retry on the next edit. Check mount "
                    "ownership/permissions (UID/GID envs).",
                    state.disk_path,
                )

    def _flush(self, state: _DocState) -> None:
        # Synchronous by design: it reads `state.doc` (pycrdt Docs are only
        # ever touched on the loop thread) and does blocking file writes, with
        # nothing to await. Callers invoke it inline on the loop thread.
        #
        # This is the ONE reconcile-and-write step: both the debounced flush
        # loop (memory→disk) and the watcher's `reconcile_external` (disk→memory)
        # funnel through here, so a single 3-way-merge policy governs both
        # directions instead of the two paths disagreeing on who wins.
        content = str(state.doc.get(TEXT_KEY, type=Text))
        merged = content
        if state.disk_path.exists():
            disk_now = read_md(state.disk_path, self._vault_dir)
            if disk_now != state.last_disk_content and disk_now != content:
                # Disk diverged from our last-synced baseline since we last
                # wrote — an external writer (Syncthing/Obsidian) landed between
                # reconciles. 3-way merge it against the baseline rather than
                # clobbering either side: non-overlapping edits from both sides
                # combine; a region both sides changed keeps OURS live and
                # spills THEIRS into a Syncthing-style conflict file.
                merged, conflict = self._three_way_merge(state.last_disk_content, content, disk_now)
                if conflict:
                    self._write_conflict_file(state.disk_path, disk_now)
                if merged != content:
                    # Replay the folded-in disk hunks as Y.Text splices so the
                    # change fans out to connected clients (ghost-editor style).
                    self._apply_ghost_merge(state, content, merged)
        write_md_atomic(state.disk_path, merged, self._vault_dir)
        # Persist the binary CRDT state so the next load can rehydrate items
        # with their original IDs instead of generating new ones from text.
        # The cache is an optimization, never load-bearing — a failure here
        # (unwritable CACHE_DIR mount) must not undo the vault write above or
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
        state.last_disk_content = merged

    async def reconcile_external(self, disk_path: Path) -> None:
        """Fold an external on-disk change to an actively-loaded `.md` into its
        in-memory Doc. This is the disk→memory trigger; it delegates the actual
        reconciliation to `_flush`, so both directions share one 3-way-merge
        policy (non-overlapping edits combine; a region both sides changed keeps
        the live doc and spills disk into a conflict file). The merged result is
        written back to disk and fans out to clients through the normal
        `on_event` path — as if a ghost typed it.

        No-op for idle notes (not in `_docs`): those reconcile lazily via the
        cold-open `_load` path on next open, deliberately, to avoid blob-cache
        churn for files nobody is using. Self-writes (our own atomic flush) are
        filtered by comparing the disk bytes against `last_disk_content`, which
        `_flush` set to exactly what we wrote — this is also what stops the
        flush→watcher→flush loop."""
        key = str(disk_path.resolve())
        async with self._lock:
            state = self._docs.get(key)
            if state is None:
                return
            # An external `rm` of a live file is out of scope for the merge —
            # the REST delete path (kick + purge) owns removal; here we keep the
            # live doc as the source of truth.
            if not disk_path.exists():
                return
            try:
                disk_content = read_md(disk_path, self._vault_dir)
            except OSError, VaultPathError:
                return
            # Self-write filter: our own flush left `last_disk_content` equal to
            # what it wrote, so nothing external actually happened. Skipping the
            # flush here is what breaks the write→event→write loop.
            if disk_content == state.last_disk_content:
                return
            self._flush(state)

    @staticmethod
    def _three_way_merge(base: str, ours: str, theirs: str) -> tuple[str, bool]:
        """Line-based 3-way merge against the common `base`. Returns the merged
        text and whether any region was changed by BOTH sides (a real conflict).

        Regions only one side touched are taken from that side; regions both
        touched keep OURS (the live doc is the winner) and raise the conflict
        flag so the caller can spill THEIRS into a Syncthing-style conflict file.
        Lines are split `keepends` so the join round-trips byte-for-byte,
        including a missing trailing newline."""
        base_l = base.splitlines(keepends=True)
        ours_l = ours.splitlines(keepends=True)
        theirs_l = theirs.splitlines(keepends=True)

        o_map = DocumentManager._unchanged_line_map(base_l, ours_l)
        t_map = DocumentManager._unchanged_line_map(base_l, theirs_l)
        # Sync points: base lines that survive UNCHANGED into both sides. They
        # partition the buffers into independently-mergeable regions. Matching
        # blocks are monotonic, so the mapped indices rise with the base index —
        # every region slice below is therefore non-negative in width.
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
        """base-line-index → other-line-index for every base line that survives
        unchanged into `other`, from `SequenceMatcher`'s matching blocks.
        `autojunk=False` — its heuristic misbehaves on large/repetitive text."""
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
        return ours_c, True  # true conflict — live doc (ours) wins

    @staticmethod
    def _apply_ghost_merge(state: _DocState, current: str, disk_content: str) -> None:
        """Transform the live `Y.Text` from `current` into `disk_content` by
        replaying `SequenceMatcher` opcodes as splices in one transaction.
        Opcodes are applied in reverse so each edit's indices stay valid — a
        splice only shifts positions at or after it, and later opcodes hold
        higher indices."""
        text = state.doc.get(TEXT_KEY, type=Text)
        opcodes = difflib.SequenceMatcher(a=current, b=disk_content, autojunk=False).get_opcodes()
        with state.doc.transaction():
            for tag, i1, i2, j1, j2 in reversed(opcodes):
                if tag == "equal":
                    continue
                if tag in ("replace", "delete"):
                    del text[i1:i2]
                if tag in ("replace", "insert"):
                    text.insert(i1, disk_content[j1:j2])

    async def rename(self, src_doc_id: str, dst_doc_id: str) -> None:
        """Kick everyone attached to `src` (so they stop editing into a Doc
        whose underlying file is about to move) and move the binary cache to
        `dst` so subsequent acquires preserve the CRDT item IDs. Clients see
        the close code `DOC_MOVED_CODE` and `reason = dst_doc_id`, which the
        frontend uses to offer a "follow" link to the new location."""
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
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        conflict = original.with_name(f"{original.stem}.sync-conflict-{ts}.md")
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
            self._flush(state)
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
