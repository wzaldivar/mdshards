"""y-websocket-compatible WebSocket endpoint.

Each client gets its own task that drives one half of the y-protocol handshake
(SYNC_STEP1 / SYNC_STEP2 / SYNC_UPDATE) plus optional awareness relay. Document
state is owned by the `DocumentManager` instance held on `app.state`.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pycrdt import (
    YMessageType,
    create_sync_message,
    create_update_message,
    handle_sync_message,
)

from .config import get_settings
from .docs import DOC_DELETED_CODE, DOC_MOVED_CODE, DocumentManager, KickSignal
from .vault import VaultPathError, resolve_md

router = APIRouter()

# Re-export the protocol codes so existing test imports keep working.
__all__ = [
    "router",
    "DOC_DELETED_CODE",
    "DOC_MOVED_CODE",
    "create_sync_message",
    "create_update_message",
    "handle_sync_message",
]


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
    if not disk_path.exists():
        await ws.close(code=DOC_DELETED_CODE, reason="deleted")
        return

    await ws.accept()
    manager: DocumentManager = ws.app.state.doc_manager
    state = await manager.acquire(doc_id)
    queue: asyncio.Queue[bytes | KickSignal] = asyncio.Queue()
    state.subscribers.add(queue)

    await ws.send_bytes(create_sync_message(state.doc))

    async def writer() -> None:
        """Push doc updates / awareness to the client. A `KickSignal` from the
        queue tells us to close the WebSocket with the given code/reason —
        used by the delete and rename paths to notify attached clients."""
        try:
            while True:
                msg = await queue.get()
                if isinstance(msg, KickSignal):
                    with suppress(Exception):
                        await ws.close(code=msg.code, reason=msg.reason)
                    return
                await ws.send_bytes(msg)
        except (WebSocketDisconnect, RuntimeError):
            return

    writer_task = asyncio.create_task(writer())

    try:
        while True:
            data = await ws.receive_bytes()
            if not data:
                continue
            msg_type = data[0]
            if msg_type == YMessageType.SYNC:
                reply = handle_sync_message(data[1:], state.doc)
                if reply is not None:
                    await ws.send_bytes(reply)
            elif msg_type == YMessageType.AWARENESS:
                for q in state.subscribers:
                    if q is not queue:
                        q.put_nowait(data)
    except WebSocketDisconnect:
        pass
    finally:
        writer_task.cancel()
        with suppress(asyncio.CancelledError):
            await writer_task
        state.subscribers.discard(queue)
        await manager.release(doc_id)
