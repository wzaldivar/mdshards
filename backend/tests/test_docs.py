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


async def _persist(mgr: DocumentManager, state) -> None:
    """Force an OUT flush now — persist memory→disk + cache, the way the flush
    loop does. (Replaces the old synchronous `mgr._flush(state)` these tests
    leaned on before IN/OUT were split.)"""
    async with state.io_lock:
        await mgr._flush_out(state)


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
        # ...holding the same text — from the cache if still within the
        # validity window, else seeded fresh from the just-flushed disk file.
        assert str(b.doc.get(TEXT_KEY, type=Text)) == "persisted"
    finally:
        await mgr.shutdown()


# ---- external-writer + rename edges (the data-loss-adjacent paths) ----


@pytest.mark.asyncio
async def test_reconcile_external_noops_when_file_vanished(tmp_path: Path) -> None:
    """A watcher event for a file deleted between event and handling must not
    touch the live doc — the delete/rename flows own that transition."""
    (tmp_path / "foo.md").write_text("alive")
    mgr = _mgr(tmp_path)
    try:
        state = await mgr.acquire("foo")
        (tmp_path / "foo.md").unlink()
        await mgr.reconcile_external(tmp_path / "foo.md")
        assert str(state.doc.get(TEXT_KEY, type=Text)) == "alive"
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_self_write_event_is_a_noop(tmp_path: Path) -> None:
    """A watcher event whose disk bytes hash-match our golden snapshot (our own
    write, or a no-op touch) changes nothing and writes no conflict file — the
    O(1) golden-hash self-write filter."""
    (tmp_path / "foo.md").write_text("same text")
    mgr = _mgr(tmp_path)
    try:
        state = await mgr.acquire("foo")
        golden_before = state.golden_hash
        await mgr.reconcile_external(tmp_path / "foo.md")
        assert str(state.doc.get(TEXT_KEY, type=Text)) == "same text"
        assert state.golden_hash == golden_before
        assert not list(tmp_path.glob("*conflict*"))
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_reconcile_external_is_multibyte_safe(tmp_path: Path) -> None:
    """The ghost merge translates SequenceMatcher's code-point indices into
    the UTF-8 byte offsets pycrdt's Text actually speaks. Regression: a pure
    ASCII external edit BELOW a multibyte character (é/ö) used to land skewed
    ('second li changedne') because every byte offset past the é was off by
    the multibyte surplus."""
    (tmp_path / "foo.md").write_text("héllo wörld\nsecond line\n")
    mgr = _mgr(tmp_path)
    try:
        state = await mgr.acquire("foo")
        (tmp_path / "foo.md").write_text("héllo wörld\nsecond line changed\n")
        await mgr.reconcile_external(tmp_path / "foo.md")
        assert str(state.doc.get(TEXT_KEY, type=Text)) == "héllo wörld\nsecond line changed\n"
        assert not list(tmp_path.glob("*conflict*"))
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_disjoint_merge_combines_with_multibyte_on_both_sides(tmp_path: Path) -> None:
    """Disjoint live + external edits combine in a doc holding 2-byte (í) and
    4-byte (emoji) characters: the external hunk splices at its correct
    position even though the live doc has already diverged further down."""
    baseline = "títle\n\nmiddle ✏️ line\n\nend\n"
    (tmp_path / "foo.md").write_text(baseline)
    mgr = _mgr(tmp_path)
    try:
        state = await mgr.acquire("foo")
        # Pause the auto-flush so the baseline stays put while both sides diverge.
        assert state.flush_task is not None
        state.flush_task.cancel()
        with suppress(asyncio.CancelledError):
            await state.flush_task
        state.flush_task = None

        state.doc.get(TEXT_KEY, type=Text).__iadd__("appended (web)\n")  # ours: EOF
        (tmp_path / "foo.md").write_text("títle!\n\nmiddle ✏️ line\n\nend\n")  # theirs: line 1

        await mgr.reconcile_external(tmp_path / "foo.md")

        merged = "títle!\n\nmiddle ✏️ line\n\nend\nappended (web)\n"
        assert str(state.doc.get(TEXT_KEY, type=Text)) == merged
        assert not list(tmp_path.glob("*conflict*"))
        await _persist(mgr, state)
        assert (tmp_path / "foo.md").read_text() == merged
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_flush_loop_survives_rust_panic(tmp_path: Path) -> None:
    """A pyo3 panic is BaseException, not Exception — the flush loop's guard
    must catch it and keep the loop alive (log-and-retry), or one bad splice
    turns into silent, total write loss for the doc."""
    from app.docs import FLUSH_QUIET_SECONDS, _RustPanic

    (tmp_path / "foo.md").write_text("content")
    mgr = _mgr(tmp_path)
    try:
        state = await mgr.acquire("foo")

        async def boom(_state) -> bool:
            raise _RustPanic("simulated Rust panic")

        mgr._flush_out = boom  # type: ignore[method-assign]
        state.flush_pending.set()
        await asyncio.sleep(FLUSH_QUIET_SECONDS + 0.2)
        assert state.flush_task is not None and not state.flush_task.done()
    finally:
        mgr._flush_out = type(mgr)._flush_out.__get__(mgr)  # restore for shutdown
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_rename_moves_the_binary_cache(tmp_path: Path) -> None:
    """rename() must carry the .yjs cache to the destination so re-acquires
    preserve CRDT item IDs across the move."""
    (tmp_path / "foo.md").write_text("content")
    mgr = _mgr(tmp_path)
    try:
        a = await mgr.acquire("foo")
        a.doc.get(TEXT_KEY, type=Text).__iadd__("!")
        await mgr.release("foo")
    finally:
        await mgr.shutdown()

    mgr2 = _mgr(tmp_path)
    try:
        cache_root = tmp_path / "_yjs_cache_"
        assert list(cache_root.rglob("foo.md.yjs")), "precondition: cache exists"
        await mgr2.rename("foo", "sub/bar")
        assert not list(cache_root.rglob("foo.md.yjs"))
        assert list(cache_root.rglob("bar.md.yjs"))
        # a rename with no cache behind it is a clean no-op
        await mgr2.rename("never-loaded", "elsewhere")
    finally:
        await mgr2.shutdown()


# ---- flush resilience ----
#
# A permissions problem on a mount must never become SILENT write loss:
# the flush loop's task exception is never retrieved (the task object stays
# referenced), so before these guards a single failed flush killed all
# future flushes for the doc with zero log output.


@pytest.mark.asyncio
async def test_cache_write_failure_does_not_block_vault_flush(tmp_path: Path, monkeypatch) -> None:
    """The .yjs cache is an optimization — an unwritable CACHE_DIR must not
    stop the vault write or poison the flush loop."""
    from app import docs as docs_module

    def _boom(*args, **kwargs):
        raise PermissionError("cache mount is read-only")

    monkeypatch.setattr(docs_module, "write_bytes_atomic", _boom)
    mgr = _mgr(tmp_path)
    try:
        a = await mgr.acquire("foo")
        a.doc.get(TEXT_KEY, type=Text).__iadd__("survives cache failure")
        await asyncio.sleep(1.0)
        assert (tmp_path / "foo.md").read_text() == "survives cache failure"
        # ...and the loop is still alive: a second edit flushes too.
        a.doc.get(TEXT_KEY, type=Text).__iadd__(" twice")
        await asyncio.sleep(1.0)
        assert (tmp_path / "foo.md").read_text() == "survives cache failure twice"
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_flush_loop_survives_vault_write_failure(tmp_path: Path, monkeypatch, caplog) -> None:
    """A failing vault write is logged loudly and retried on the next edit
    instead of killing the flush task forever."""
    from app import docs as docs_module

    real_write = docs_module.write_md_atomic
    fail = {"active": True}

    def _flaky(*args, **kwargs):
        if fail["active"]:
            raise PermissionError("vault mount owned by root")
        return real_write(*args, **kwargs)

    monkeypatch.setattr(docs_module, "write_md_atomic", _flaky)
    mgr = _mgr(tmp_path)
    try:
        a = await mgr.acquire("foo")
        with caplog.at_level("ERROR", logger="mdshards.docs"):
            a.doc.get(TEXT_KEY, type=Text).__iadd__("lost edit")
            await asyncio.sleep(1.0)
        assert not (tmp_path / "foo.md").exists()
        assert any("FAILED" in r.message for r in caplog.records), "failed flush must be logged"
        # Mount fixed; the NEXT edit re-arms the loop and lands everything.
        fail["active"] = False
        a.doc.get(TEXT_KEY, type=Text).__iadd__(" recovered")
        await asyncio.sleep(1.0)
        assert (tmp_path / "foo.md").read_text() == "lost edit recovered"
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_unreadable_cache_degrades_to_fresh_disk_load(tmp_path: Path, monkeypatch) -> None:
    """An unreadable .yjs cache file must not make the note unopenable —
    the load falls back to seeding from the on-disk markdown."""
    (tmp_path / "foo.md").write_text("disk truth")
    mgr = _mgr(tmp_path)
    try:
        a = await mgr.acquire("foo")
        a.doc.get(TEXT_KEY, type=Text).__iadd__("!")
        await mgr.release("foo")
    finally:
        await mgr.shutdown()  # writes the cache file

    cache_files = list((tmp_path / "_yjs_cache_").rglob("*.yjs"))
    assert cache_files, "precondition: shutdown persisted a cache file"
    real_read_bytes = Path.read_bytes

    def _unreadable(self: Path):
        if self.suffix == ".yjs":
            raise PermissionError("cache mount unreadable")
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", _unreadable)
    mgr2 = _mgr(tmp_path)
    try:
        state = await mgr2.acquire("foo")
        assert str(state.doc.get(TEXT_KEY, type=Text)) == "disk truth!"
    finally:
        monkeypatch.setattr(Path, "read_bytes", real_read_bytes)
        await mgr2.shutdown()


@pytest.mark.asyncio
async def test_teardown_survives_a_failing_final_flush(tmp_path: Path, monkeypatch, caplog) -> None:
    """The final flush at eviction/shutdown is best-effort: one bad doc must
    not abort the shutdown loop (dropping OTHER docs' final flushes) — it
    logs and moves on."""
    from app import docs as docs_module

    mgr = _mgr(tmp_path)
    a = await mgr.acquire("doomed")
    a.doc.get(TEXT_KEY, type=Text).__iadd__("unflushable")
    b = await mgr.acquire("healthy")
    b.doc.get(TEXT_KEY, type=Text).__iadd__("flushable")

    real_write = docs_module.write_md_atomic

    def _selective(path, *args, **kwargs):
        if path.name == "doomed.md":
            raise PermissionError("mount went read-only")
        return real_write(path, *args, **kwargs)

    monkeypatch.setattr(docs_module, "write_md_atomic", _selective)
    with caplog.at_level("ERROR", logger="mdshards.docs"):
        await mgr.shutdown()  # must not raise
    assert (tmp_path / "healthy.md").read_text() == "flushable"
    assert any("final flush" in r.message for r in caplog.records)


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
async def test_conflict_moves_ours_to_conflict_and_keeps_fs(tmp_path: Path) -> None:
    """Both sides change the same region → git-style unapplyable → conflict. The
    web side (ours) is preserved in an `.mdshards-conflict-` file and its clients
    are kicked there (DOC_MOVED); the main file keeps the FS version (we can't
    merge it without noise); the doc is dropped."""
    (tmp_path / "foo.md").write_text("baseline")
    mgr = _mgr(tmp_path)
    try:
        state = await mgr.acquire("foo")
        # Pause the auto-flush so the baseline stays "baseline" (an early flush
        # would advance it and turn this into a clean disk-wins update).
        assert state.flush_task is not None
        state.flush_task.cancel()
        with suppress(asyncio.CancelledError):
            await state.flush_task
        state.flush_task = None

        q: asyncio.Queue[bytes | KickSignal] = asyncio.Queue()
        state.subscribers.add(q)
        state.doc.get(TEXT_KEY, type=Text).__iadd__(" edited")  # ours diverges
        (tmp_path / "foo.md").write_text("external write")  # theirs diverges, same region

        await mgr.reconcile_external(tmp_path / "foo.md")

        conflicts = list(tmp_path.glob("foo.mdshards-conflict-*.md"))
        assert len(conflicts) == 1
        assert conflicts[0].read_text() == "baseline edited"  # ours preserved
        assert (tmp_path / "foo.md").read_text() == "external write"  # FS canonical
        drained = []
        while not q.empty():
            drained.append(q.get_nowait())
        kicks = [s for s in drained if isinstance(s, KickSignal)]
        assert len(kicks) == 1
        assert kicks[0].code == DOC_MOVED_CODE
        assert kicks[0].reason == conflicts[0].stem  # kicked to the conflict file
        assert str((tmp_path / "foo.md").resolve()) not in mgr._docs
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
        await _persist(mgr, state)
        assert list(tmp_path.glob("foo.*conflict-*.md")) == []
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
        await _persist(mgr1, s)
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
    """The WITHIN-validity-window case (default grace keeps the cache fresh
    here): a reconnecting client may still hold matching CRDT items, so the
    cache is restored — Doc keeps the cached text and the diverged disk
    content is preserved as a conflict file. The stale-cache case is the
    opposite: see test_stale_cache_is_dropped_and_disk_wins."""
    mgr1 = _mgr(tmp_path)
    try:
        s = await mgr1.acquire("foo")
        s.doc.get(TEXT_KEY, type=Text).__iadd__("from the editor")
        await _persist(mgr1, s)
    finally:
        await mgr1.shutdown()

    # Some other process rewrites the .md while the server is down.
    (tmp_path / "foo.md").write_text("from disk")

    mgr2 = _mgr(tmp_path)
    try:
        s2 = await mgr2.acquire("foo")
        # Live Doc keeps the cached text — the user's CRDT state takes priority.
        assert str(s2.doc.get(TEXT_KEY, type=Text)) == "from the editor"
        conflicts = list(tmp_path.glob("foo.mdshards-conflict-*.md"))
        assert len(conflicts) == 1
        assert conflicts[0].read_text() == "from disk"
    finally:
        await mgr2.shutdown()


@pytest.mark.asyncio
async def test_stale_cache_is_dropped_and_disk_wins(tmp_path: Path) -> None:
    """Cold open with a cache older than the validity window: every client
    that could still hold matching CRDT items has been dismissed (client-side
    threshold = grace), so the cache is dropped and disk seeds the doc fresh —
    no stale text, no spurious conflict file. This is the idle-note path of
    the primary flow: edit in the web, leave it, edit in Obsidian (the watcher
    skips idle notes by design), reopen in the web days later."""
    mgr1 = _mgr(tmp_path)
    try:
        s = await mgr1.acquire("foo")
        s.doc.get(TEXT_KEY, type=Text).__iadd__("from the editor")
        await _persist(mgr1, s)
    finally:
        await mgr1.shutdown()

    (tmp_path / "foo.md").write_text("from disk")  # external edit while idle

    await asyncio.sleep(0.2)  # let the cache age past mgr2's validity window
    mgr2 = _mgr(tmp_path, grace_period_seconds=0.05)
    try:
        s2 = await mgr2.acquire("foo")
        assert str(s2.doc.get(TEXT_KEY, type=Text)) == "from disk"
        assert not list(tmp_path.glob("*conflict*"))
    finally:
        await mgr2.shutdown()


def test_cache_max_age_defaults_to_grace_and_clamps_up(tmp_path: Path) -> None:
    """Unset → the grace period. Longer → honored (more item-ID continuity,
    still safe: dismissal is client-side regardless). Shorter → clamped up,
    or a quick server restart would reintroduce the double-merge the cache
    exists to prevent."""
    cache = tmp_path / "cache"
    assert DocumentManager(tmp_path, 30.0, cache)._cache_max_age == 30.0
    assert (
        DocumentManager(tmp_path, 30.0, cache, cache_max_age_seconds=300.0)._cache_max_age == 300.0
    )
    assert DocumentManager(tmp_path, 30.0, cache, cache_max_age_seconds=5.0)._cache_max_age == 30.0


@pytest.mark.asyncio
async def test_conflict_purges_cache_so_reopen_gets_fs_version(tmp_path: Path) -> None:
    """The conflict kick must drop the blob cache along with the doc: the cache
    still holds the web-side text that just moved to the conflict file, and
    restoring it on the next open would demote the canonical FS version into a
    SECOND conflict file — inverting FS-is-king."""
    (tmp_path / "foo.md").write_text("baseline")
    mgr = _mgr(tmp_path)
    try:
        state = await mgr.acquire("foo")
        await _persist(mgr, state)  # cache now holds the web-side state
        assert state.flush_task is not None
        state.flush_task.cancel()
        with suppress(asyncio.CancelledError):
            await state.flush_task
        state.flush_task = None

        state.doc.get(TEXT_KEY, type=Text).__iadd__(" edited")  # ours diverges
        (tmp_path / "foo.md").write_text("external write")  # theirs, same region
        await mgr.reconcile_external(tmp_path / "foo.md")

        assert not mgr._cache_path(tmp_path / "foo.md").exists()

        s2 = await mgr.acquire("foo")
        assert str(s2.doc.get(TEXT_KEY, type=Text)) == "external write"  # FS canonical
        # exactly the one conflict file from the kick — reopening created no second
        assert len(list(tmp_path.glob("foo.mdshards-conflict-*.md"))) == 1
    finally:
        await mgr.shutdown()


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
async def test_kick_delete_records_root_forward(tmp_path: Path) -> None:
    """A delete-kick records a forward to root ("") so a client that dropped
    without the DOC_DELETED close code (Safari) can still be sent home."""
    (tmp_path / "foo.md").write_text("x")
    mgr = _mgr(tmp_path)
    try:
        await mgr.acquire("foo")
        await mgr.kick("foo")  # default = DOC_DELETED
        assert mgr.forward_target("foo") == ""
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
        await _persist(mgr, s)
        src_cache = mgr._cache_path(s.disk_path)
        assert src_cache.exists()

        await mgr.rename("notes/old", "renamed")

        # Subscribers got the move-flavored kick (code 4002 + dst as reason).
        signal = q.get_nowait()
        assert isinstance(signal, KickSignal)
        assert signal.code == DOC_MOVED_CODE
        assert signal.reason == "renamed"
        # The forward is queryable too (Safari side channel via GET /api/moved).
        assert mgr.forward_target("notes/old") == "renamed"
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
        await _persist(mgr, s)
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
        await _persist(mgr1, kept)
        await _persist(mgr1, gone)
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
        await _persist(mgr, a)
        await _persist(mgr, b)
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
