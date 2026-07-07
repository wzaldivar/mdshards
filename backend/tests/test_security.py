"""Tests for the Origin/Sec-Fetch-Site guards.

On /api/* and /ws/*: requests MUST carry `Sec-Fetch-Site` in the
same-origin / same-site / none set — browsers send this on every request,
curl by default doesn't. That's the curl-bypass block.

On static paths (/, /assets, /favicon, vault assets): looser gate
preserved — safe methods pass unconditionally, only state-changing requests
check origin. Typed URLs and bookmarks must keep working.

The `client` fixture defaults to `Sec-Fetch-Site: same-origin` so it stands
in for a real browser. The `bare_client` fixture omits the header to
represent the curl / scripted caller we're trying to block.
"""

import pytest
from starlette.websockets import WebSocketDisconnect

# ---- HTTP ----


def test_browser_safe_methods_on_api_pass(client) -> None:
    """Browser-style GETs to /api/* (Sec-Fetch-Site=same-origin via the
    fixture default) are accepted."""
    c, _ = client
    assert c.get("/api/tree").status_code == 200
    assert c.get("/api/resolve").status_code == 200


def test_browser_post_without_explicit_origin_is_allowed(client) -> None:
    """A POST that omits Origin but carries Sec-Fetch-Site=same-origin
    represents a same-origin browser fetch (some browsers omit Origin on
    same-origin POSTs). The middleware accepts it because the
    browser-fingerprint header is present and not cross-site."""
    c, _ = client
    r = c.post("/api/files", json={"path": "scripted"})
    assert r.status_code == 201


def test_post_same_origin_is_allowed(client) -> None:
    c, _ = client
    r = c.post(
        "/api/files",
        json={"path": "same_origin"},
        headers={"origin": "http://testserver"},
    )
    assert r.status_code == 201


def test_post_cross_origin_is_blocked(client) -> None:
    c, _ = client
    r = c.post(
        "/api/files",
        json={"path": "evil"},
        headers={"origin": "https://evil.example.com"},
    )
    assert r.status_code == 403


def test_post_sec_fetch_site_cross_site_is_blocked(client) -> None:
    """Modern browsers send Sec-Fetch-Site even when Origin is absent. Treat
    `cross-site` as authoritative."""
    c, _ = client
    r = c.post(
        "/api/files",
        json={"path": "evil"},
        headers={"sec-fetch-site": "cross-site"},
    )
    assert r.status_code == 403


def test_delete_cross_origin_is_blocked(client) -> None:
    c, vault = client
    (vault / "x.md").write_text("")
    r = c.delete("/api/files/x", headers={"origin": "https://evil.example.com"})
    assert r.status_code == 403
    assert (vault / "x.md").exists()


def test_asset_upload_cross_origin_is_blocked(client) -> None:
    """The multipart simple-request CSRF vector that motivated this — proves
    the middleware catches the form-style cross-origin upload."""
    c, vault = client
    r = c.post(
        "/api/assets",
        data={"path": "evil.png"},
        files={"file": ("evil.png", b"x", "image/png")},
        headers={"origin": "https://evil.example.com"},
    )
    assert r.status_code == 403
    assert not (vault / "evil.png").exists()


# ---- HTTP: the curl-bypass block ----
#
# These use `bare_client` (no default browser-fingerprint headers) to verify
# that a raw caller like `curl` can't reach /api/* or /ws/*.


def test_bare_get_on_api_is_blocked(bare_client) -> None:
    """curl /api/tree (no Sec-Fetch-Site) → 403."""
    c, _ = bare_client
    assert c.get("/api/tree").status_code == 403
    assert c.get("/api/resolve").status_code == 403


def test_bare_post_on_api_is_blocked(bare_client) -> None:
    c, vault = bare_client
    r = c.post("/api/files", json={"path": "curl_bypass"})
    assert r.status_code == 403
    assert not (vault / "curl_bypass.md").exists()


def test_bare_delete_on_api_is_blocked(bare_client) -> None:
    c, vault = bare_client
    (vault / "victim.md").write_text("")
    r = c.delete("/api/files/victim")
    assert r.status_code == 403
    assert (vault / "victim.md").exists()


def test_bare_asset_upload_is_blocked(bare_client) -> None:
    c, vault = bare_client
    r = c.post(
        "/api/assets",
        data={"path": "evil.png"},
        files={"file": ("evil.png", b"x", "image/png")},
    )
    assert r.status_code == 403
    assert not (vault / "evil.png").exists()


def test_bare_get_on_static_path_still_works(bare_client) -> None:
    """The block applies ONLY to /api/* and /ws/*. Typed-URL nav to / or to
    a vault page must still work without browser-fingerprint headers."""
    c, _ = bare_client
    assert c.get("/").status_code == 200


# ---- WebSocket ----


def test_browser_ws_without_sec_fetch_site_is_allowed(bare_client) -> None:
    """Regression: real browsers omit ALL Sec-Fetch-* metadata on the WS
    opening handshake but always send `Origin`. Such a handshake (Origin
    present, no Sec-Fetch-Site) must be accepted — an earlier guard required
    Sec-Fetch-Site on /ws and rejected every real browser connection.

    Uses `bare_client` (no fixture-injected Sec-Fetch-Site) with only Origin
    set, to reproduce exactly what a browser sends."""
    c, vault = bare_client
    (vault / "x.md").write_text("hi")
    with c.websocket_connect("/ws/x", headers={"origin": "http://testserver"}) as ws:
        assert ws.receive_bytes()  # SYNC_STEP1


def test_bare_ws_is_blocked(bare_client) -> None:
    """A WS upgrade with no Origin (a raw non-browser caller) is closed
    before accept — browsers always send Origin on the handshake, so its
    absence marks the casual curl/script bypass. Only the bundle reaches
    /ws."""
    c, vault = bare_client
    (vault / "x.md").write_text("hi")
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with c.websocket_connect("/ws/x"):
            pass
    assert exc_info.value.code == 1008


def test_ws_same_origin_is_allowed(client) -> None:
    c, vault = client
    (vault / "x.md").write_text("hi")
    with c.websocket_connect("/ws/x", headers={"origin": "http://testserver"}) as ws:
        assert ws.receive_bytes()


def test_ws_cross_origin_is_blocked(client) -> None:
    c, vault = client
    (vault / "x.md").write_text("hi")
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with c.websocket_connect("/ws/x", headers={"origin": "https://evil.example.com"}):
            pass
    assert exc_info.value.code == 1008


def test_ws_sec_fetch_site_cross_site_is_blocked(client) -> None:
    c, vault = client
    (vault / "x.md").write_text("hi")
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with c.websocket_connect("/ws/x", headers={"sec-fetch-site": "cross-site"}):
            pass
    assert exc_info.value.code == 1008
