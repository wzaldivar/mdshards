"""In-memory CRDT document lifecycle: load on first connect, persist on change,
linger for a grace period after the last client leaves, then evict.

The on-disk `.md` is the source of truth; `Doc` instances exist only to mediate
concurrent edits. See CLAUDE.md for the lifecycle and conflict-policy rules.
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import os
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pycrdt import Doc, Subscription, Text, create_update_message

from .files import read_md, write_bytes_atomic, write_md_atomic
from .vault import VaultPathError, assert_inside, resolve_md

FLUSH_QUIET_SECONDS = 0.5
TEXT_KEY = "content"

# Ghost-merge trust thresholds (see `reconcile_external`). `SequenceMatcher` is
# not a minimal diff and degrades on large/repetitive text, so a diff that turns
# out to be an almost-total rewrite is treated as untrustworthy: we drop a
# Syncthing-style conflict file rather than ghost-apply garbage into the live
# doc. Small buffers legitimately rewrite wholesale, so the ratio gate only
# applies once both sides exceed `_GHOST_MIN_LEN`.
_GHOST_MIN_RATIO = 0.4
_GHOST_MIN_LEN = 200

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
        if cache_path.exists():
            # Restore the prior CRDT state with all its original item IDs so
            # clients still holding a Y.Doc from before can sync against the
            # SAME items rather than getting "the same text again" as fresh
            # inserts (which would duplicate on merge).
            doc.apply_update(cache_path.read_bytes())
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
        # cleanup needed), so there's no try/except to wrap the loop in.
        while True:
            await state.flush_pending.wait()
            while state.flush_pending.is_set():
                state.flush_pending.clear()
                await asyncio.sleep(FLUSH_QUIET_SECONDS)
            self._flush(state)

    def _flush(self, state: _DocState) -> None:
        # Synchronous by design: it reads `state.doc` (pycrdt Docs are only
        # ever touched on the loop thread) and does blocking file writes, with
        # nothing to await. Callers invoke it inline on the loop thread.
        content = str(state.doc.get(TEXT_KEY, type=Text))
        if state.disk_path.exists():
            disk_now = read_md(state.disk_path, self._vault_dir)
            if disk_now != state.last_disk_content and disk_now != content:
                self._write_conflict_file(state.disk_path, disk_now)
        write_md_atomic(state.disk_path, content, self._vault_dir)
        # Persist the binary CRDT state so the next load can rehydrate items
        # with their original IDs instead of generating new ones from text.
        write_bytes_atomic(
            self._cache_path(state.disk_path),
            state.doc.get_update(b"\x00"),
            self._cache_root,
        )
        state.last_disk_content = content

    async def reconcile_external(self, disk_path: Path) -> None:
        """Fold an external on-disk change to an actively-loaded `.md` into its
        in-memory Doc, ghost-editor style (stage 2). Diffs the new disk bytes
        against the live text and replays the opcodes as `Y.Text` splices in one
        transaction, so the change fans out to connected clients through the
        normal `on_event` path — as if a ghost typed it — and is never applied
        by overwriting the file.

        No-op for idle notes (not in `_docs`): those reconcile lazily via the
        cold-open `_load` path on next open, deliberately, to avoid blob-cache
        churn for files nobody is using. Self-writes (our own atomic flush) are
        filtered by comparing the disk bytes against `last_disk_content`, which
        `_flush` set to exactly what we wrote. An untrustworthy diff writes a
        Syncthing-style conflict file and leaves the live doc untouched."""
        key = str(disk_path.resolve())
        async with self._lock:
            state = self._docs.get(key)
            if state is None:
                return
            # An external `rm` of a live file is out of scope for the
            # ghost-merge — the REST delete path (kick + purge) owns removal;
            # here we keep the live doc as the source of truth.
            if not disk_path.exists():
                return
            try:
                disk_content = read_md(disk_path, self._vault_dir)
            except (OSError, VaultPathError):
                return
            # Self-write filter: our own flush left `last_disk_content` equal to
            # what it wrote, so nothing external actually happened.
            if disk_content == state.last_disk_content:
                return
            current = str(state.doc.get(TEXT_KEY, type=Text))
            if disk_content == current:
                # Already in sync — e.g. a self-write whose `last_disk_content`
                # update raced this event. Record the baseline and stop.
                state.last_disk_content = disk_content
                return
            if not self._diff_is_trustworthy(current, disk_content):
                self._write_conflict_file(disk_path, disk_content)
                # Adopt disk as the known baseline so the passive `_flush` path
                # doesn't emit a SECOND conflict file for the same divergence;
                # the unchanged live doc wins back to disk on the next flush.
                state.last_disk_content = disk_content
                return
            self._apply_ghost_merge(state, current, disk_content)
            state.last_disk_content = disk_content

    @staticmethod
    def _diff_is_trustworthy(current: str, disk: str) -> bool:
        """Whether the `current` → `disk` diff is safe to ghost-apply. Below
        `_GHOST_MIN_LEN` on both sides a full rewrite is legitimate and cheap,
        so trust it. Above that, a similarity ratio under `_GHOST_MIN_RATIO`
        means the buffers share almost nothing — an unreliable diff, so bail to
        a conflict file. `autojunk=False` disables the heuristic that misbehaves
        on large/repetitive markdown."""
        if len(current) < _GHOST_MIN_LEN and len(disk) < _GHOST_MIN_LEN:
            return True
        sm = difflib.SequenceMatcher(a=current, b=disk, autojunk=False)
        return sm.ratio() >= _GHOST_MIN_RATIO

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
        self._flush(state)

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
