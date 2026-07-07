"""Stage-2 external-writer reconciliation.

Most tests drive `DocumentManager.reconcile_external` directly — the ghost-merge
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
        await mgr._flush(state)  # our own write; sets last_disk_content
        # A watcher event for our own flush must not disturb the doc.
        await mgr.reconcile_external(state.disk_path)
        assert _text(state) == "typed by a client"
        assert list(tmp_path.glob("*.sync-conflict-*.md")) == []
    finally:
        await mgr.shutdown()


@pytest.mark.asyncio
async def test_untrustworthy_diff_writes_conflict_file(tmp_path: Path) -> None:
    original = "a" * 500
    (tmp_path / "foo.md").write_text(original)
    mgr = _mgr(tmp_path)
    try:
        state = await mgr.acquire("foo")
        # A near-total rewrite of a large buffer: SequenceMatcher shares almost
        # nothing, so we must NOT ghost-apply — we drop a conflict file.
        state.disk_path.write_text("b" * 500)
        await mgr.reconcile_external(state.disk_path)
        assert _text(state) == original  # live doc untouched
        conflicts = list(tmp_path.glob("foo.sync-conflict-*.md"))
        assert len(conflicts) == 1
        assert conflicts[0].read_text() == "b" * 500
    finally:
        await mgr.shutdown()


def test_diff_trustworthiness_thresholds() -> None:
    # Small buffers legitimately rewrite wholesale.
    assert DocumentManager._diff_is_trustworthy("cat", "dog") is True
    # Large, similar → trustworthy.
    base = "line\n" * 200
    assert DocumentManager._diff_is_trustworthy(base, base + "extra\n") is True
    # Large, near-disjoint → untrustworthy.
    assert DocumentManager._diff_is_trustworthy("a" * 500, "b" * 500) is False


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
