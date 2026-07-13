import asyncio
from contextlib import suppress
from pathlib import Path

import pytest
from pycrdt import Text

from app.docs import (
    DOC_DELETED_CODE,
    DOC_MOVED_CODE,
    TEXT_KEY,
    DocumentManager,
    KickSignal,
)


def _mgr(vault: Path, *, grace_period_seconds: float = 10.0) -> DocumentManager:
    """Build a DocumentManager for tests, with the binary cache isolated under
    the test's tmp tree so each test gets a fresh cache namespace."""
    return DocumentManager(
        vault_dir=vault,
        grace_period_seconds=grace_period_seconds,
        cache_dir=vault / "_yjs_cache_",
    )


@pytest.mark.asyncio
async def test_first_acquire_loads_disk_content(tmp_path: Path) -> None:
    (tmp_path / "foo.md").write_text("hello from disk")
    mgr = _mgr(tmp_path)
    try:
        state = await mgr.acquire("foo")
        assert str(state.doc.get(TEXT_KEY, type=Text)) == "hello from disk"
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_acquire_twice_returns_same_state(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    try:
        a = await mgr.acquire("foo")
        b = await mgr.acquire("foo")
        assert a is b
        assert a.refcount == 2
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_reconnect_within_grace_reuses_doc(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path, grace_period_seconds=2.0)
    try:
        a = await mgr.acquire("foo")
        a.doc.get(TEXT_KEY, type=Text).__iadd__("abc")  # text += "abc"
        await mgr.release("foo")
        b = await mgr.acquire("foo")
        assert b is a
        assert str(b.doc.get(TEXT_KEY, type=Text)) == "abc"
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_eviction_persists_and_drops(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path, grace_period_seconds=0.05)
    try:
        a = await mgr.acquire("foo")
        a.doc.get(TEXT_KEY, type=Text).__iadd__("persisted")
        await mgr.release("foo")
        # Wait beyond grace
        await asyncio.sleep(0.3)
        assert (tmp_path / "foo.md").read_text() == "persisted"
        # Re-acquire should give a different state instance...
        b = await mgr.acquire("foo")
        assert b is not a
        # ...but with the cache in place, the rebuilt Doc holds the same text.
        assert str(b.doc.get(TEXT_KEY, type=Text)) == "persisted"
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_debounced_flush_writes_on_quiet(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    try:
        a = await mgr.acquire("foo")
        a.doc.get(TEXT_KEY, type=Text).__iadd__("typing...")
        # Within quiet window, file may not yet exist.
        await asyncio.sleep(1.0)
        assert (tmp_path / "foo.md").read_text() == "typing..."
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_conflict_file_written_on_external_divergence(tmp_path: Path) -> None:
    """If the disk file is modified by an external writer while the doc holds
    divergent state, the divergent disk content gets written to a Syncthing-style
    sync-conflict file and the live doc's content lands at the original path."""
    (tmp_path / "foo.md").write_text("baseline")
    mgr = _mgr(tmp_path)
    try:
        state = await mgr.acquire("foo")
        # Pause the auto-flush task so we control timing exactly.
        assert state.flush_task is not None
        state.flush_task.cancel()
        with suppress(asyncio.CancelledError):
            await state.flush_task
        state.flush_task = None

        state.doc.get(TEXT_KEY, type=Text).__iadd__(" edited")
        assert str(state.doc.get(TEXT_KEY, type=Text)) == "baseline edited"

        # External writer overwrites the file with divergent content.
        (tmp_path / "foo.md").write_text("external write")

        mgr._flush(state)

        conflicts = list(tmp_path.glob("foo.sync-conflict-*.md"))
        assert len(conflicts) == 1
        assert conflicts[0].read_text() == "external write"
        assert (tmp_path / "foo.md").read_text() == "baseline edited"
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_root_and_index_aliases_share_state(tmp_path: Path) -> None:
    """`""` (vault root) and `"index"` both resolve to <vault>/index.md, so the
    DocumentManager must hand back the same Doc for either spelling."""
    mgr = _mgr(tmp_path)
    try:
        a = await mgr.acquire("")
        b = await mgr.acquire("index")
        assert a is b
        assert a.refcount == 2
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_no_conflict_when_disk_matches_in_memory(tmp_path: Path) -> None:
    (tmp_path / "foo.md").write_text("same")
    mgr = _mgr(tmp_path)
    try:
        state = await mgr.acquire("foo")
        mgr._flush(state)
        conflicts = list(tmp_path.glob("foo.sync-conflict-*.md"))
        assert conflicts == []
    finally:
        await mgr.shutdown()


# --- binary cache --------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_preserves_item_ids_across_manager_recreate(tmp_path: Path) -> None:
    """Edit, shut down, rebuild the manager, edit again — the state vector
    should grow monotonically (no fresh client-IDs replacing old ones), which
    is what prevents duplicate-merge on client reconnect."""
    mgr1 = _mgr(tmp_path)
    try:
        s = await mgr1.acquire("foo")
        s.doc.get(TEXT_KEY, type=Text).__iadd__("hello")
        sv_before = s.doc.get_state()
        mgr1._flush(s)
    finally:
        await mgr1.shutdown()

    mgr2 = _mgr(tmp_path)
    try:
        s2 = await mgr2.acquire("foo")
        assert str(s2.doc.get(TEXT_KEY, type=Text)) == "hello"
        # State vector encodes (client_id → next_clock). After a cache-restore
        # the SAME clients should appear; adding the contents of the old state
        # vector to the new one must be a strict superset (same keys, same or
        # higher clocks). The simplest invariant we can check without parsing
        # the Yjs varint format is that the byte representation matches.
        assert s2.doc.get_state() == sv_before
    finally:
        await mgr2.shutdown()


@pytest.mark.asyncio
async def test_external_disk_write_after_cache_writes_conflict(tmp_path: Path) -> None:
    """Cache says one thing, disk says another → conflict file from disk,
    Doc keeps the cached text."""
    mgr1 = _mgr(tmp_path)
    try:
        s = await mgr1.acquire("foo")
        s.doc.get(TEXT_KEY, type=Text).__iadd__("from the editor")
        mgr1._flush(s)
    finally:
        await mgr1.shutdown()

    # Some other process rewrites the .md while the server is down.
    (tmp_path / "foo.md").write_text("from disk")

    mgr2 = _mgr(tmp_path)
    try:
        s2 = await mgr2.acquire("foo")
        # Live Doc keeps the cached text — the user's CRDT state takes priority.
        assert str(s2.doc.get(TEXT_KEY, type=Text)) == "from the editor"
        conflicts = list(tmp_path.glob("foo.sync-conflict-*.md"))
        assert len(conflicts) == 1
        assert conflicts[0].read_text() == "from disk"
    finally:
        await mgr2.shutdown()


@pytest.mark.asyncio
async def test_kick_drops_state_and_signals_subscribers(tmp_path: Path) -> None:
    """`kick` should remove the doc from the manager and push a `KickSignal`
    into every subscriber queue so the WS handler can close those connections
    with a deletion close code."""
    mgr = _mgr(tmp_path)
    try:
        state = await mgr.acquire("foo")
        q1: asyncio.Queue[bytes | KickSignal] = asyncio.Queue()
        q2: asyncio.Queue[bytes | KickSignal] = asyncio.Queue()
        state.subscribers.add(q1)
        state.subscribers.add(q2)

        await mgr.kick("foo")

        s1 = q1.get_nowait()
        s2 = q2.get_nowait()
        assert isinstance(s1, KickSignal) and s1.code == DOC_DELETED_CODE
        assert isinstance(s2, KickSignal) and s2.code == DOC_DELETED_CODE
        # State is no longer tracked; a fresh acquire builds a new instance.
        again = await mgr.acquire("foo")
        assert again is not state
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_kick_does_not_flush(tmp_path: Path) -> None:
    """Kick must not persist — the file is being deleted, so flushing would
    resurrect it after the delete completes."""
    mgr = _mgr(tmp_path)
    try:
        s = await mgr.acquire("foo")
        s.doc.get(TEXT_KEY, type=Text).__iadd__("about to be deleted")
        await mgr.kick("foo")
        # No `foo.md` should be written by kick.
        assert not (tmp_path / "foo.md").exists()
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_rename_moves_cache_and_kicks_clients(tmp_path: Path) -> None:
    """`rename` must (a) kick everyone attached to the old path so they stop
    editing into a Doc that's about to move, and (b) relocate the cache file
    so the new path resumes with the same CRDT item IDs."""
    mgr = _mgr(tmp_path)
    try:
        s = await mgr.acquire("notes/old")
        s.doc.get(TEXT_KEY, type=Text).__iadd__("history")
        q: asyncio.Queue[bytes | None] = asyncio.Queue()
        s.subscribers.add(q)
        mgr._flush(s)
        src_cache = mgr._cache_path(s.disk_path)
        assert src_cache.exists()

        await mgr.rename("notes/old", "renamed")

        # Subscribers got the move-flavored kick (code 4002 + dst as reason).
        signal = q.get_nowait()
        assert isinstance(signal, KickSignal)
        assert signal.code == DOC_MOVED_CODE
        assert signal.reason == "renamed"
        # Source cache moved, source parent dir pruned, dest cache present.
        assert not src_cache.exists()
        dst_disk = tmp_path / "renamed.md"
        dst_cache = mgr._cache_path(dst_disk)
        assert dst_cache.exists()
        assert not src_cache.parent.exists()
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_purge_removes_cache_file(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    try:
        s = await mgr.acquire("notes/today")
        s.doc.get(TEXT_KEY, type=Text).__iadd__("x")
        cache_path = mgr._cache_path(s.disk_path)
        mgr._flush(s)
        assert cache_path.exists()
        await mgr.release("notes/today")
        mgr.purge("notes/today")
        assert not cache_path.exists()
        # Empty parent dirs under the cache root should be cleaned up too.
        assert not cache_path.parent.exists()
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_prune_orphaned_cache_drops_files_with_no_md(tmp_path: Path) -> None:
    """A note deleted from the vault while the server was down should not
    have its cached CRDT state resurrected at startup."""
    mgr1 = _mgr(tmp_path)
    try:
        kept = await mgr1.acquire("kept")
        gone = await mgr1.acquire("gone")
        kept.doc.get(TEXT_KEY, type=Text).__iadd__("k")
        gone.doc.get(TEXT_KEY, type=Text).__iadd__("g")
        mgr1._flush(kept)
        mgr1._flush(gone)
        kept_cache = mgr1._cache_path(kept.disk_path)
        gone_cache = mgr1._cache_path(gone.disk_path)
        assert kept_cache.exists() and gone_cache.exists()
    finally:
        await mgr1.shutdown()

    # Simulate an external delete of `gone.md` while we were offline.
    (tmp_path / "gone.md").unlink()

    mgr2 = _mgr(tmp_path)
    try:
        removed = mgr2.prune_orphaned_cache()
        assert removed == 1
        assert kept_cache.exists()
        assert not gone_cache.exists()
    finally:
        await mgr2.shutdown()


@pytest.mark.asyncio
async def test_two_docs_get_distinct_cache_files(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    try:
        a = await mgr.acquire("foo")
        b = await mgr.acquire("bar")
        a.doc.get(TEXT_KEY, type=Text).__iadd__("A")
        b.doc.get(TEXT_KEY, type=Text).__iadd__("B")
        mgr._flush(a)
        mgr._flush(b)
        ca = mgr._cache_path(a.disk_path)
        cb = mgr._cache_path(b.disk_path)
        assert ca != cb
        assert ca.exists() and cb.exists()
        assert ca.read_bytes() != cb.read_bytes()
    finally:
        await mgr.shutdown()


# --- cache-root containment ---------------------------------------------------


def test_unlink_cache_rejects_path_outside_cache_root(tmp_path: Path) -> None:
    """The cache primitive must self-defend the same way the vault primitives
    do — a caller that constructs a bogus cache path should hit `VaultPathError`
    before any unlink runs."""
    from app.vault import VaultPathError

    mgr = _mgr(tmp_path)
    outside = tmp_path.parent / f"outside_{tmp_path.name}"
    outside.mkdir(exist_ok=True)
    bystander = outside / "bystander.yjs"
    bystander.write_bytes(b"keep")
    with pytest.raises(VaultPathError):
        mgr._unlink_cache(bystander)
    assert bystander.exists()


def test_cache_path_stays_inside_cache_root(tmp_path: Path) -> None:
    """Every `_cache_path` result must live under the per-vault cache root —
    the assertion inside `_cache_path` is the guard."""
    mgr = _mgr(tmp_path)
    disk = tmp_path / "deeply" / "nested" / "note.md"
    disk.parent.mkdir(parents=True)
    disk.write_text("x")
    cache_path = mgr._cache_path(disk)
    assert cache_path.is_relative_to(mgr._cache_root.resolve())
