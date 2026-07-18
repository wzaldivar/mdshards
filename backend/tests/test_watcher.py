"""Stage-2 external-writer reconciliation.

Most tests drive `DocumentManager.reconcile_external` directly — the 3-way-merge
logic — to stay deterministic. The final test wires up a real `watchdog`
observer end to end to prove events actually reach the reconciler.
"""

import asyncio
from contextlib import suppress
from pathlib import Path

import pytest
from pycrdt import Text

from app.docs import DOC_MOVED_CODE, TEXT_KEY, DocumentManager, KickSignal
from app.watcher import VaultWatcher


def _mgr(vault: Path, *, grace_period_seconds: float = 10.0) -> DocumentManager:
    return DocumentManager(
        vault_dir=vault,
        grace_period_seconds=grace_period_seconds,
        cache_dir=vault / "_yjs_cache_",
    )


def _text(state) -> str:
    return str(state.doc.get(TEXT_KEY, type=Text))


async def _persist(mgr: DocumentManager, state) -> None:
    async with state.io_lock:
        await mgr._flush_out(state)


def _drain(q: asyncio.Queue) -> list:
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    return items


async def _pause_flush(state) -> None:
    """Stop the debounced flush task so a test controls the merge base exactly
    (an early flush would advance last_disk_content and change the merge)."""
    if state.flush_task is not None:
        state.flush_task.cancel()
        with suppress(asyncio.CancelledError):
            await state.flush_task
        state.flush_task = None


# --- ghost-merge --------------------------------------------------------------


@pytest.mark.asyncio
async def test_external_edit_ghost_merges_into_live_doc(tmp_path: Path) -> None:
    (tmp_path / "foo.md").write_text("hello world")
    mgr = _mgr(tmp_path)
    try:
        state = await mgr.acquire("foo")
        assert _text(state) == "hello world"
        # External writer inserts a word mid-buffer.
        state.disk_path.write_text("hello brave world")
        await mgr.reconcile_external(state.disk_path)
        assert _text(state) == "hello brave world"
        assert state.last_disk_content == "hello brave world"
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_ghost_merge_fans_out_to_subscribers(tmp_path: Path) -> None:
    (tmp_path / "foo.md").write_text("abc")
    mgr = _mgr(tmp_path)
    try:
        state = await mgr.acquire("foo")
        queue: asyncio.Queue = asyncio.Queue()
        state.subscribers.add(queue)
        state.disk_path.write_text("abcdef")
        await mgr.reconcile_external(state.disk_path)
        # The transaction fired `on_event`, which pushed an update onto every
        # subscriber queue — that's how connected clients see the ghost edit.
        assert not queue.empty()
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_idle_note_is_not_reconciled(tmp_path: Path) -> None:
    (tmp_path / "bar.md").write_text("untouched")
    mgr = _mgr(tmp_path)
    try:
        from app.vault import resolve_md

        path = resolve_md("bar", tmp_path)
        # Never acquired → not loaded. Must be a no-op, not a load.
        await mgr.reconcile_external(path)
        assert str(path.resolve()) not in mgr._docs
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_self_write_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "foo.md").write_text("")
    mgr = _mgr(tmp_path)
    try:
        state = await mgr.acquire("foo")
        state.doc.get(TEXT_KEY, type=Text).__iadd__("typed by a client")
        await _persist(mgr, state)  # our own write; sets the golden hash
        # A watcher event for our own flush hash-matches golden → no-op.
        await mgr.reconcile_external(state.disk_path)
        assert _text(state) == "typed by a client"
        assert list(tmp_path.glob("*conflict-*.md")) == []
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_disjoint_edits_merge(tmp_path: Path) -> None:
    """A disk hunk that lands away from the live edit applies cleanly (git-style)
    — both survive. The live doc prepends a line; disk appends one; they combine,
    no conflict file."""
    (tmp_path / "foo.md").write_text("a\nb\nc\n")
    mgr = _mgr(tmp_path)
    try:
        state = await mgr.acquire("foo")
        await _pause_flush(state)  # keep the base at the original three lines
        state.doc.get(TEXT_KEY, type=Text).insert(0, "TOP\n")  # ours: prepend
        state.disk_path.write_text("a\nb\nc\nBOT\n")  # theirs: append
        await mgr.reconcile_external(state.disk_path)
        assert _text(state) == "TOP\na\nb\nc\nBOT\n"  # both preserved
        assert list(tmp_path.glob("*conflict-*.md")) == []
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_overlapping_edit_conflicts_and_kicks(tmp_path: Path) -> None:
    """Both sides change the SAME line → the disk hunk can't apply over the live
    edit → conflict. Ours goes to an `.mdshards-conflict-` file, its clients are
    kicked there (DOC_MOVED), the FS version stays canonical, the doc is dropped."""
    (tmp_path / "foo.md").write_text("a\nb\nc\n")
    mgr = _mgr(tmp_path)
    try:
        state = await mgr.acquire("foo")
        await _pause_flush(state)
        q: asyncio.Queue = asyncio.Queue()
        state.subscribers.add(q)
        text = state.doc.get(TEXT_KEY, type=Text)
        del text[2:3]
        text.insert(2, "B")  # ours: middle line b -> B
        state.disk_path.write_text("a\nXYZ\nc\n")  # theirs: middle line b -> XYZ
        await mgr.reconcile_external(state.disk_path)
        conflicts = list(tmp_path.glob("foo.mdshards-conflict-*.md"))
        assert len(conflicts) == 1
        assert conflicts[0].read_text() == "a\nB\nc\n"  # ours preserved
        assert (tmp_path / "foo.md").read_text() == "a\nXYZ\nc\n"  # FS canonical
        kicks = [_q for _q in _drain(q) if isinstance(_q, KickSignal)]
        assert len(kicks) == 1
        assert kicks[0].code == DOC_MOVED_CODE
        assert kicks[0].reason == conflicts[0].stem  # kicked to the conflict file
        assert str((tmp_path / "foo.md").resolve()) not in mgr._docs
        # The forward is also queryable (the Safari side channel): a client that
        # dropped without the close code can still find the conflict file.
        assert mgr.forward_target("foo") == conflicts[0].stem
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_pure_external_change_costs_no_disk_write(tmp_path: Path) -> None:
    """An external edit with no competing memory change folds into the live doc
    and triggers zero mdshards writes — the follow-up flush finds memory == disk
    (golden-hash match) and skips. Verified via the file's mtime staying put."""
    (tmp_path / "foo.md").write_text("hello")
    mgr = _mgr(tmp_path)
    try:
        state = await mgr.acquire("foo")
        state.disk_path.write_text("hello world")
        mtime_before = state.disk_path.stat().st_mtime_ns
        await mgr.reconcile_external(state.disk_path)
        assert _text(state) == "hello world"
        # A flush right after must NOT rewrite the file (memory already == disk).
        await _persist(mgr, state)
        assert state.disk_path.stat().st_mtime_ns == mtime_before
        assert state.disk_path.read_text() == "hello world"
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_external_rewrite_folds_in_wholesale(tmp_path: Path) -> None:
    """A near-total external rewrite with no competing memory edit just folds in
    — no conflict file."""
    (tmp_path / "foo.md").write_text("a" * 500)
    mgr = _mgr(tmp_path)
    try:
        state = await mgr.acquire("foo")
        state.disk_path.write_text("b" * 500)
        await mgr.reconcile_external(state.disk_path)
        assert _text(state) == "b" * 500
        assert list(tmp_path.glob("*conflict-*.md")) == []
    finally:
        await mgr.shutdown()


# --- end-to-end through a real watchdog observer ------------------------------


@pytest.mark.asyncio
async def test_observer_dispatches_external_edit(tmp_path: Path) -> None:
    (tmp_path / "foo.md").write_text("start")
    mgr = _mgr(tmp_path)
    watcher = VaultWatcher(mgr, tmp_path)
    watcher.start(asyncio.get_running_loop())
    try:
        state = await mgr.acquire("foo")
        state.disk_path.write_text("start and then some")
        # Poll: the observer runs on its own thread and schedules the reconcile
        # onto our loop; give it time to land.
        for _ in range(100):
            if _text(state) == "start and then some":
                break
            await asyncio.sleep(0.1)
        assert _text(state) == "start and then some"
    finally:
        watcher.stop()
        await mgr.shutdown()
