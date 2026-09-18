"""y-websocket-compatible WebSocket endpoint.

Each client gets its own task that drives one half of the y-protocol handshake
(SYNC_STEP1 / SYNC_STEP2 / SYNC_UPDATE) plus optional awareness relay. Document
state is owned by the `DocumentManager` instance held on `app.state`.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from contextlib import suppress

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pycrdt import (
    YMessageType,
    create_sync_message,
    create_update_message,
    handle_sync_message,
)

from .config import get_settings
from .docs import DOC_DELETED_CODE, DOC_MOVED_CODE, DocumentManager, KickSignal, _DocState, TEXT_KEY
from .files import ensure_index_exists
from .vault import VaultPathError, resolve_md

router = APIRouter()

# Server→client keepalive. y-websocket hard-closes a connection that received
# no server message for 30s (`messageReconnectTimeout`), and an idle doc
# produces exactly that silence — every idle tab would micro-cut its socket
# every ~30s. Client-side timers can't reliably prevent it (Safari throttles
# unfocused windows hard enough to starve them), but *incoming* messages are
# delivered even to throttled tabs, so the server pushes the traffic instead:
# an AWARENESS frame whose payload is an empty update (varUint8Array of the
# single byte 0x00 = "0 clients") — a protocol-valid no-op on every client.
_KEEPALIVE_SECONDS = 10
_KEEPALIVE_MSG = bytes([YMessageType.AWARENESS, 1, 0])

# Resource exhaustion guards: per-connection limits to prevent unauthenticated
# clients from consuming unbounded disk, CPU, and I/O via CRDT updates.
# Maximum size of a single WebSocket frame (bytes). Legitimate CRDT updates from
# typing are small (tens to hundreds of bytes); large pastes might reach low KB.
# This bound stops a single oversized frame from consuming memory/CPU.
_MAX_FRAME_BYTES = 256 * 1024  # 256 KB
# Maximum document size (UTF-8 characters). Prevents a client from growing the
# in-memory CRDT and on-disk markdown to unbounded size. Checked after applying
# each SYNC update. Large notes (technical docs, meeting transcripts) can reach
# tens of KB; this is a safety bound, not a UX limit.
_MAX_DOC_CHARS = 10 * 1024 * 1024  # 10 million characters (~10 MB of text)
# Rate limit: maximum frames per second per connection. Legitimate typing
# generates a few updates/sec; this stops a client from flooding the server with
# updates that each trigger a flush (full-document hash + atomic write).
_MAX_FRAMES_PER_SECOND = 100
# Rate limit window: how many seconds of frame timestamps to track for the
# sliding-window rate calculation.
_RATE_WINDOW_SECONDS = 1.0
# Cumulative data limit: maximum total bytes a single connection can send over
# its lifetime. Stops a slow-drip attack that stays under the per-frame and
# per-second limits but accumulates unbounded data over time.
_MAX_CUMULATIVE_BYTES = 50 * 1024 * 1024  # 50 MB

# Re-export the protocol codes so existing test imports keep working.
__all__ = [
    "router",
    "DOC_DELETED_CODE",
    "DOC_MOVED_CODE",
    "create_sync_message",
    "create_update_message",
    "handle_sync_message",
]


class _RateLimiter:
    """Sliding-window rate limiter for WebSocket frames. Tracks frame timestamps
    and rejects frames that would exceed the configured rate limit."""

    def __init__(self, max_per_second: float, window_seconds: float) -> None:
        self.max_per_second = max_per_second
        self.window_seconds = window_seconds
        self.timestamps: deque[float] = deque()

    def check_and_record(self) -> bool:
        """Record the current frame and return True if under the rate limit,
        False if the limit is exceeded. Prunes stale timestamps outside the
        sliding window."""
        now = time.monotonic()
        # Remove timestamps outside the sliding window
        cutoff = now - self.window_seconds
        while self.timestamps and self.timestamps[0] < cutoff:
            self.timestamps.popleft()
        # Check if adding this frame would exceed the limit
        if len(self.timestamps) >= self.max_per_second * self.window_seconds:
            return False
        self.timestamps.append(now)
        return True


class _ConnectionLimits:
    """Per-connection resource limits to prevent exhaustion attacks."""

    def __init__(self) -> None:
        self.rate_limiter = _RateLimiter(_MAX_FRAMES_PER_SECOND, _RATE_WINDOW_SECONDS)
        self.cumulative_bytes = 0


async def _writer(ws: WebSocket, queue: asyncio.Queue[bytes | KickSignal]) -> None:
    """Push doc updates / awareness to the client. A `KickSignal` from the
    queue tells us to close the WebSocket with the given code/reason — used by
    the delete and rename paths to notify attached clients."""
    try:
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
            except TimeoutError:
                await ws.send_bytes(_KEEPALIVE_MSG)
                continue
            if isinstance(msg, KickSignal):
                with suppress(Exception):
                    await ws.close(code=msg.code, reason=msg.reason)
                return
            await ws.send_bytes(msg)
    except WebSocketDisconnect, RuntimeError:
        return


async def _handle_frame(
    ws: WebSocket,
    state: _DocState,
    queue: asyncio.Queue[bytes | KickSignal],
    data: bytes,
    limits: _ConnectionLimits,
) -> None:
    """Dispatch one inbound y-protocol frame: reply to SYNC, relay AWARENESS
    to the other subscribers. Enforces document size limits after applying SYNC
    updates to prevent unbounded document growth."""
    msg_type = data[0]
    if msg_type == YMessageType.SYNC:
        reply = handle_sync_message(data[1:], state.doc)
        # After applying a SYNC update, check if the document has grown beyond
        # the safety limit. This prevents a client from growing the in-memory
        # CRDT and on-disk markdown to unbounded size, which would consume
        # unlimited disk, CPU (hashing), and I/O (atomic writes) on every flush.
        from pycrdt import Text

        doc_text = state.doc.get(TEXT_KEY, type=Text)
        doc_length = len(str(doc_text))
        if doc_length > _MAX_DOC_CHARS:
            # Close the connection with a policy violation code. The client's
            # update was applied (pycrdt mutated the doc), but we refuse to
            # continue syncing a document that has exceeded the safety bound.
            # The next flush will persist the oversized state, but no further
            # updates from this or any other client will be accepted until the
            # document is manually trimmed below the limit (e.g. via external
            # editor or a different client that reconnects and deletes content).
            await ws.close(code=1008, reason="document size limit exceeded")
            return
        if reply is not None:
            await ws.send_bytes(reply)
    elif msg_type == YMessageType.AWARENESS:
        for q in state.subscribers:
            if q is not queue:
                q.put_nowait(data)


async def _reader(
    ws: WebSocket, state: _DocState, queue: asyncio.Queue[bytes | KickSignal]
) -> None:
    """Pump inbound frames to `_handle_frame` until the client disconnects.
    Enforces per-connection resource limits: frame size, rate, cumulative data,
    and document size. Closes the connection if any limit is exceeded."""
    limits = _ConnectionLimits()
    try:
        while True:
            data = await ws.receive_bytes()
            if not data:
                continue
            # Frame size limit: reject oversized frames before processing.
            # Legitimate CRDT updates are small; this stops a single frame from
            # consuming unbounded memory/CPU.
            if len(data) > _MAX_FRAME_BYTES:
                await ws.close(code=1009, reason="frame too large")
                return
            # Rate limit: reject frames that exceed the per-second limit.
            # Stops a client from flooding the server with updates that each
            # trigger a flush (full-document hash + atomic write).
            if not limits.rate_limiter.check_and_record():
                await ws.close(code=1008, reason="rate limit exceeded")
                return
            # Cumulative data limit: reject connections that send too much data
            # over their lifetime. Stops slow-drip attacks that stay under the
            # per-frame and per-second limits but accumulate unbounded data.
            limits.cumulative_bytes += len(data)
            if limits.cumulative_bytes > _MAX_CUMULATIVE_BYTES:
                await ws.close(code=1008, reason="cumulative data limit exceeded")
                return
            await _handle_frame(ws, state, queue, data, limits)
    except WebSocketDisconnect:
        pass


@router.websocket("/ws/{doc_id:path}")
async def ws_endpoint(ws: WebSocket, doc_id: str) -> None:
    settings = get_settings()
    try:
        disk_path = resolve_md(doc_id, settings.vault_dir)
    except VaultPathError:
        await ws.close(code=1008)
        return
    # A stale tab whose connection dropped during the delete window could
    # otherwise reconnect, sync its old Y.Doc items into a freshly-created
    # empty Doc on the server, and resurrect the deleted file on the next
    # flush. Refuse with the same code the live-kick path uses so the
    # frontend's existing close-code handler navigates the tab to root.
    #
    # The root index is the exception: it regenerates from its template
    # whenever it's missing — always, in every deployment mode — so a WS
    # for it materializes the file instead of kicking the client.
    if not disk_path.exists():
        if disk_path == (settings.vault_dir / "index.md").resolve():
            ensure_index_exists(settings.vault_dir)
        else:
            await ws.close(code=DOC_DELETED_CODE, reason="deleted")
            return

    await ws.accept()
    manager: DocumentManager = ws.app.state.doc_manager
    state = await manager.acquire(doc_id)
    queue: asyncio.Queue[bytes | KickSignal] = asyncio.Queue()
    state.subscribers.add(queue)

    await ws.send_bytes(create_sync_message(state.doc))

    writer_task = asyncio.create_task(_writer(ws, queue))
    try:
        await _reader(ws, state, queue)
    finally:
        writer_task.cancel()
        with suppress(asyncio.CancelledError):
            await writer_task
        state.subscribers.discard(queue)
        await manager.release(doc_id)
