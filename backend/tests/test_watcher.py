"""Stage-2 external-writer reconciliation.

Most tests drive `DocumentManager.reconcile_external` directly — the 3-way-merge
logic — to stay deterministic. The final test wires up a real `watchdog`
observer end to end to prove events actually reach the reconciler.
"""

import asyncio
from pathlib import Path

import pytest
from pycrdt import Text

from app.docs import TEXT_KEY, DocumentManager
from app.watcher import VaultWatcher


def _mgr(vault: Path, *, grace_period_seconds: float = 10.0) -> DocumentManager:
    return DocumentManager(
        vault_dir=vault,
        grace_period_seconds=grace_period_seconds,
        cache_dir=vault / "_yjs_cache_",
    )


def _text(state) -> str:
    return str(state.doc.get(TEXT_KEY, type=Text))


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
        mgr._flush(state)  # our own write; sets last_disk_content
        # A watcher event for our own flush must not disturb the doc.
        await mgr.reconcile_external(state.disk_path)
        assert _text(state) == "typed by a client"
        assert list(tmp_path.glob("*.sync-conflict-*.md")) == []
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_non_overlapping_edits_merge_without_conflict(tmp_path: Path) -> None:
    """Both sides edit the SAME file but DIFFERENT regions: the 3-way merge
    combines them and writes no conflict file. Base is the three-line file both
    started from; the client prepends a line, disk appends one."""
    (tmp_path / "foo.md").write_text("a\nb\nc\n")
    mgr = _mgr(tmp_path)
    try:
        state = await mgr.acquire("foo")
        # Local (client) edit: prepend a line — this is "ours".
        state.doc.get(TEXT_KEY, type=Text).insert(0, "TOP\n")
        # External edit against the SAME baseline: append a line — "theirs".
        state.disk_path.write_text("a\nb\nc\nBOT\n")
        await mgr.reconcile_external(state.disk_path)
        assert _text(state) == "TOP\na\nb\nc\nBOT\n"
        assert list(tmp_path.glob("*.sync-conflict-*.md")) == []
        # Merged result was written back to disk and adopted as the baseline.
        assert (tmp_path / "foo.md").read_text() == "TOP\na\nb\nc\nBOT\n"
        assert state.last_disk_content == "TOP\na\nb\nc\nBOT\n"
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_overlapping_edits_conflict_ours_wins_theirs_to_file(tmp_path: Path) -> None:
    """Both sides change the SAME line: a real conflict. The live doc (ours)
    wins in-memory and on disk; the disk version spills to a conflict file."""
    (tmp_path / "foo.md").write_text("a\nb\nc\n")
    mgr = _mgr(tmp_path)
    try:
        state = await mgr.acquire("foo")
        text = state.doc.get(TEXT_KEY, type=Text)
        del text[2:3]  # "a\nb\nc\n" -> "a\nB\nc\n" via replace of the middle line
        text.insert(2, "B")
        assert _text(state) == "a\nB\nc\n"
        # External writer changes the SAME middle line differently.
        state.disk_path.write_text("a\nXYZ\nc\n")
        await mgr.reconcile_external(state.disk_path)
        assert _text(state) == "a\nB\nc\n"  # ours wins live
        assert (tmp_path / "foo.md").read_text() == "a\nB\nc\n"  # and on disk
        conflicts = list(tmp_path.glob("foo.sync-conflict-*.md"))
        assert len(conflicts) == 1
        assert conflicts[0].read_text() == "a\nXYZ\nc\n"  # theirs preserved
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_external_rewrite_without_local_edit_is_not_a_conflict(tmp_path: Path) -> None:
    """A near-total external rewrite with NO competing local edit is just an
    update, not a conflict — it folds in wholesale, no conflict file. (Under
    the old ratio heuristic this wrote a conflict file; the 3-way merge only
    conflicts when both sides touched the same region.)"""
    (tmp_path / "foo.md").write_text("a" * 500)
    mgr = _mgr(tmp_path)
    try:
        state = await mgr.acquire("foo")
        state.disk_path.write_text("b" * 500)
        await mgr.reconcile_external(state.disk_path)
        assert _text(state) == "b" * 500
        assert list(tmp_path.glob("foo.sync-conflict-*.md")) == []
    finally:
        await mgr.shutdown()


def test_three_way_merge_classifies_regions() -> None:
    m = DocumentManager._three_way_merge
    # Only theirs changed → take theirs, no conflict.
    assert m("a\nb\n", "a\nb\n", "a\nB\n") == ("a\nB\n", False)
    # Only ours changed → take ours, no conflict.
    assert m("a\nb\n", "A\nb\n", "a\nb\n") == ("A\nb\n", False)
    # Both made the identical change → no conflict.
    assert m("a\nb\n", "a\nX\n", "a\nX\n") == ("a\nX\n", False)
    # Non-overlapping edits combine.
    assert m("a\nb\nc\n", "TOP\na\nb\nc\n", "a\nb\nc\nBOT\n") == (
        "TOP\na\nb\nc\nBOT\n",
        False,
    )
    # Same region changed differently → conflict, ours kept.
    assert m("a\nb\nc\n", "a\nB\nc\n", "a\nXYZ\nc\n") == ("a\nB\nc\n", True)


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
