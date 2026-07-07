"""Filesystem watcher (stage 2): fold external edits to actively-loaded `.md`
files into their in-memory CRDT Docs.

The motivating case is `mdshards vault <> Syncthing <> Obsidian vault` — another
tool may overwrite a `.md` while a browser is editing it. A `watchdog` observer
runs on its own thread and forwards `.md` change events to
`DocumentManager.reconcile_external`, which runs on the asyncio loop (pycrdt
Docs are only ever mutated there). Only paths currently loaded in the manager
are reconciled; idle notes reconcile lazily on next open via the cold-open path.
See CLAUDE.md ("The vault has external writers").
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .docs import DocumentManager


class _VaultEventHandler(FileSystemEventHandler):
    """Runs on the watchdog observer thread. Hands `.md` events off to the
    event loop; everything else (assets, temp files, directories) is ignored."""

    def __init__(self, manager: DocumentManager, loop: asyncio.AbstractEventLoop) -> None:
        self._manager = manager
        self._loop = loop

    def _dispatch(self, path_str: str) -> None:
        # Only markdown enters the CRDT layer. Our own atomic writes go through
        # a `.<name>.tmp` temp file (doesn't end in `.md`) then rename onto the
        # target, which arrives via `on_moved` below.
        if not path_str.endswith(".md"):
            return
        # Reconcile on the loop — pycrdt Docs are single-thread-owned there.
        # `reconcile_external` no-ops for idle notes and filters self-writes.
        asyncio.run_coroutine_threadsafe(
            self._manager.reconcile_external(Path(path_str)), self._loop
        )

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._dispatch(event.src_path)

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._dispatch(event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        # Atomic-save editors (Obsidian, Vim, our own `os.replace` flush) land
        # here: a temp file renamed onto the target. The destination holds the
        # real content.
        if not event.is_directory:
            self._dispatch(event.dest_path)


class VaultWatcher:
    """Owns the watchdog observer over the vault root. `start` must be called
    from the running event loop so it can capture it for cross-thread dispatch."""

    def __init__(self, manager: DocumentManager, vault_dir: Path) -> None:
        self._manager = manager
        self._vault_dir = vault_dir
        self._observer: Observer | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        handler = _VaultEventHandler(self._manager, loop)
        observer = Observer()
        observer.schedule(handler, str(self._vault_dir), recursive=True)
        observer.start()
        self._observer = observer

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
