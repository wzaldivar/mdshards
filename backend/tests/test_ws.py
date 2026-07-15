"""End-to-end WebSocket smoke tests: SYNC_STEP1 handshake from the server,
two-client update propagation, and graceful disconnect."""

from pycrdt import (
    Doc,
    Text,
    YMessageType,
    YSyncMessageType,
    create_sync_message,
    create_update_message,
    handle_sync_message,
)


def test_server_sends_sync_step1_on_connect(client) -> None:
    c, vault = client
    (vault / "foo.md").write_text("")
    with c.websocket_connect("/ws/foo", headers={"origin": "http://testserver"}) as ws:
        msg = ws.receive_bytes()
        assert msg[0] == YMessageType.SYNC
        assert msg[1] == YSyncMessageType.SYNC_STEP1


def test_reconnect_to_deleted_file_is_refused(client) -> None:
    """A tab that lost connection during the kick window will auto-reconnect
    via y-websocket. The server must refuse with `DOC_DELETED_CODE` instead of
    silently creating an empty Doc — otherwise the stale Y.Doc on the client
    would sync its items back and resurrect the deleted file."""
    import pytest
    from starlette.websockets import WebSocketDisconnect

    from app.ws import DOC_DELETED_CODE

    c, _ = client
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with c.websocket_connect("/ws/never_existed", headers={"origin": "http://testserver"}):
            pass
    assert exc_info.value.code == DOC_DELETED_CODE


def test_delete_kicks_attached_clients(client) -> None:
    """Deleting a `.md` while another tab is connected should drop that tab's
    WebSocket with the dedicated `DOC_DELETED_CODE` so the frontend can navigate
    away. Without this, the other client would keep editing a ghost Doc."""
    import pytest
    from starlette.websockets import WebSocketDisconnect

    from app.ws import DOC_DELETED_CODE

    c, vault = client
    (vault / "x.md").write_text("hi")
    with c.websocket_connect("/ws/x", headers={"origin": "http://testserver"}) as ws:
        ws.receive_bytes()  # drain initial SYNC_STEP1
        r = c.delete("/api/files/x")
        assert r.status_code == 200
        with pytest.raises(WebSocketDisconnect) as exc_info:
            # Any further receive on the ws should observe the server-side close.
            ws.receive_bytes()
        assert exc_info.value.code == DOC_DELETED_CODE


def test_invalid_path_closes_with_policy_violation(client) -> None:
    c, _ = client
    import pytest
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc_info:
        # Spaces are valid now; use a null byte to hit VaultPathError.
        with c.websocket_connect("/ws/foo%00bar", headers={"origin": "http://testserver"}):
            pass
    assert exc_info.value.code == 1008


def test_spaced_doc_id_connects(client) -> None:
    """A note whose name contains spaces syncs over the WS like any other —
    the client percent-encodes the room, Starlette decodes the path param."""
    c, vault = client
    (vault / "my note.md").write_text("hi")
    with c.websocket_connect("/ws/my%20note", headers={"origin": "http://testserver"}) as ws:
        assert ws.receive_bytes()  # initial SYNC_STEP1 from the server


def test_two_clients_converge(client) -> None:
    """A client that types into ws1 sees their changes echoed to ws2 via the
    server's update broadcast — the core CRDT convergence guarantee."""
    c, vault = client
    (vault / "note.md").write_text("")
    with (
        c.websocket_connect("/ws/note", headers={"origin": "http://testserver"}) as ws1,
        c.websocket_connect("/ws/note", headers={"origin": "http://testserver"}) as ws2,
    ):
        # Drain server's SYNC_STEP1 on both
        ws1.receive_bytes()
        ws2.receive_bytes()

        # ws1 acts as a yjs client: build a local doc, complete the handshake.
        client1_doc = Doc()
        client1_text = client1_doc.get("content", type=Text)
        ws1.send_bytes(create_sync_message(client1_doc))
        # server replies with SYNC_STEP2
        reply = ws1.receive_bytes()
        assert reply[0] == YMessageType.SYNC
        handle_sync_message(reply[1:], client1_doc)

        # Same for ws2.
        client2_doc = Doc()
        client2_doc.get("content", type=Text)
        ws2.send_bytes(create_sync_message(client2_doc))
        ws2.receive_bytes()  # SYNC_STEP2 for client2 (empty so far)

        # client1 types — push the resulting update to the server.
        client1_text += "hello"
        update = client1_doc.get_update(b"\x00")  # full state
        # Wrap as SYNC_UPDATE
        ws1.send_bytes(create_update_message(update))

        # client2 should receive that update broadcast.
        msg = ws2.receive_bytes()
        assert msg[0] == YMessageType.SYNC
        handle_sync_message(msg[1:], client2_doc)
        assert str(client2_doc.get("content", type=Text)) == "hello"


def test_disk_persisted_after_ws_disconnect(client) -> None:
    """A change made over WS lands on disk once the doc is evicted."""
    import time

    c, vault = client
    (vault / "note.md").write_text("")
    # Force a short grace period for the test
    c.app.state.doc_manager._grace = 0.1

    with c.websocket_connect("/ws/note", headers={"origin": "http://testserver"}) as ws:
        ws.receive_bytes()  # SYNC_STEP1
        client_doc = Doc()
        client_doc.get("content", type=Text)
        ws.send_bytes(create_sync_message(client_doc))
        ws.receive_bytes()  # SYNC_STEP2
        client_doc.get("content", type=Text).__iadd__("persisted via ws")
        ws.send_bytes(create_update_message(client_doc.get_update(b"\x00")))
    # WS closed; eviction scheduled at 0.1s; allow time for flush.
    time.sleep(0.6)
    assert (vault / "note.md").read_text() == "persisted via ws"


def test_ws_regenerates_missing_index(client) -> None:
    """The root index regenerates from its template whenever it's missing —
    in EVERY deployment mode, so the WS chokepoint (which every editor
    session passes through) materializes it instead of kicking the client
    with DOC_DELETED."""
    c, vault = client
    index = vault / "index.md"
    if index.exists():
        index.unlink()
    with c.websocket_connect("/ws/", headers={"origin": "http://testserver"}) as ws:
        ws.receive_bytes()  # server's SYNC_STEP1 — connection accepted, not kicked
    assert index.exists()
    assert "Welcome to mdshards" in index.read_text()


def test_index_is_read_only_over_ws(client) -> None:
    """The landing page (index) drops client writes: reads still flow (the page
    loads), but an update sent over its socket never mutates index.md."""
    import time

    c, vault = client
    c.app.state.doc_manager._grace = 0.1

    with c.websocket_connect("/ws/", headers={"origin": "http://testserver"}) as ws:
        ws.receive_bytes()  # server SYNC_STEP1
        client_doc = Doc()
        client_doc.get("content", type=Text)
        ws.send_bytes(create_sync_message(client_doc))
        step2 = ws.receive_bytes()  # SYNC_STEP2 — server sent us the doc (read works)
        assert step2[0] == YMessageType.SYNC
        # An attempted write is silently dropped by the read-only index socket.
        client_doc.get("content", type=Text).__iadd__("DEFACED")
        ws.send_bytes(create_update_message(client_doc.get_update(b"\x00")))
    time.sleep(0.6)  # WS closed; let the doc evict + flush
    text = (vault / "index.md").read_text()
    assert "DEFACED" not in text
    assert "Welcome to mdshards" in text
