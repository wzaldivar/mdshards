"""Tests for the Origin/Sec-Fetch-Site guards.

On /_mdshards/api/* and /_mdshards/ws/*: requests MUST carry a browser fingerprint —
`Sec-Fetch-Site` in the same-origin / same-site / none set when present,
else an `Origin` or `Referer` matching our own `Host` (browsers omit ALL
Sec-Fetch-* headers on plain-HTTP non-localhost origins). curl by default
sends none of the three. That's the curl-bypass block.

On static paths (/, /_mdshards/assets, /_mdshards/favicon.svg, vault assets): looser gate
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
    """Browser-style GETs to /_mdshards/api/* (Sec-Fetch-Site=same-origin via the
    fixture default) are accepted."""
    c, _ = client
    assert c.get("/_mdshards/api/tree").status_code == 200
    assert c.get("/_mdshards/api/resolve").status_code == 200


def test_browser_post_without_explicit_origin_is_allowed(client) -> None:
    """A POST that omits Origin but carries Sec-Fetch-Site=same-origin
    represents a same-origin browser fetch (some browsers omit Origin on
    same-origin POSTs). The middleware accepts it because the
    browser-fingerprint header is present and not cross-site."""
    c, _ = client
    r = c.post("/_mdshards/api/files", json={"path": "scripted"})
    assert r.status_code == 201


def test_post_same_origin_is_allowed(client) -> None:
    c, _ = client
    r = c.post(
        "/_mdshards/api/files",
        json={"path": "same_origin"},
        headers={"origin": "http://testserver"},
    )
    assert r.status_code == 201


def test_post_cross_origin_is_blocked(client) -> None:
    c, _ = client
    r = c.post(
        "/_mdshards/api/files",
        json={"path": "evil"},
        headers={"origin": "https://evil.example.com"},
    )
    assert r.status_code == 403


def test_post_sec_fetch_site_cross_site_is_blocked(client) -> None:
    """Modern browsers send Sec-Fetch-Site even when Origin is absent. Treat
    `cross-site` as authoritative."""
    c, _ = client
    r = c.post(
        "/_mdshards/api/files",
        json={"path": "evil"},
        headers={"sec-fetch-site": "cross-site"},
    )
    assert r.status_code == 403


def test_delete_cross_origin_is_blocked(client) -> None:
    c, vault = client
    (vault / "x.md").write_text("")
    r = c.delete("/_mdshards/api/files/x", headers={"origin": "https://evil.example.com"})
    assert r.status_code == 403
    assert (vault / "x.md").exists()


def test_asset_upload_cross_origin_is_blocked(client) -> None:
    """The multipart simple-request CSRF vector that motivated this — proves
    the middleware catches the form-style cross-origin upload."""
    c, vault = client
    r = c.post(
        "/_mdshards/api/assets",
        data={"path": "evil.png"},
        files={"file": ("evil.png", b"x", "image/png")},
        headers={"origin": "https://evil.example.com"},
    )
    assert r.status_code == 403
    assert not (vault / "evil.png").exists()


# ---- HTTP: the curl-bypass block ----
#
# These use `bare_client` (no default browser-fingerprint headers) to verify
# that a raw caller like `curl` can't reach /_mdshards/api/* or /_mdshards/ws/*.


def test_bare_get_on_api_is_blocked(bare_client) -> None:
    """curl /_mdshards/api/tree (no Sec-Fetch-Site) → 403."""
    c, _ = bare_client
    assert c.get("/_mdshards/api/tree").status_code == 403
    assert c.get("/_mdshards/api/resolve").status_code == 403


def test_bare_post_on_api_is_blocked(bare_client) -> None:
    c, vault = bare_client
    r = c.post("/_mdshards/api/files", json={"path": "curl_bypass"})
    assert r.status_code == 403
    assert not (vault / "curl_bypass.md").exists()


def test_bare_delete_on_api_is_blocked(bare_client) -> None:
    c, vault = bare_client
    (vault / "victim.md").write_text("")
    r = c.delete("/_mdshards/api/files/victim")
    assert r.status_code == 403
    assert (vault / "victim.md").exists()


def test_bare_asset_upload_is_blocked(bare_client) -> None:
    c, vault = bare_client
    r = c.post(
        "/_mdshards/api/assets",
        data={"path": "evil.png"},
        files={"file": ("evil.png", b"x", "image/png")},
    )
    assert r.status_code == 403
    assert not (vault / "evil.png").exists()


# ---- HTTP: plain-HTTP LAN fallback (no Fetch Metadata at all) ----
#
# Browsers only deliver `Sec-Fetch-*` to potentially trustworthy origins
# (https:// or localhost). A browser using the app at `http://192.168.x.x`
# sends NO Sec-Fetch-* headers on any request — only `Referer` (same-origin
# GETs under the default referrer policy) and `Origin` (non-GET fetches).
# The guard must accept those and still block callers with neither.


def test_lan_http_get_with_matching_referer_is_allowed(bare_client) -> None:
    """Same-origin GET fetch from a plain-HTTP LAN page: no Sec-Fetch-*, but
    Referer names our own host → allowed. This is the request shape that made
    the app unusable on any IP other than localhost."""
    c, _ = bare_client
    r = c.get("/_mdshards/api/tree", headers={"referer": "http://testserver/some/page"})
    assert r.status_code == 200


def test_lan_http_get_with_foreign_referer_is_blocked(bare_client) -> None:
    c, _ = bare_client
    r = c.get("/_mdshards/api/tree", headers={"referer": "http://evil.example.com/"})
    assert r.status_code == 403


def test_lan_http_post_with_matching_origin_is_allowed(bare_client) -> None:
    """Non-GET fetches always carry Origin; over plain HTTP it must stand in
    for the absent Sec-Fetch-Site."""
    c, vault = bare_client
    r = c.post(
        "/_mdshards/api/files",
        json={"path": "lan_note"},
        headers={"origin": "http://testserver"},
    )
    assert r.status_code == 201
    assert (vault / "lan_note.md").exists()


def test_lan_http_post_with_foreign_origin_is_blocked(bare_client) -> None:
    c, vault = bare_client
    r = c.post(
        "/_mdshards/api/files",
        json={"path": "evil"},
        headers={"origin": "http://evil.example.com"},
    )
    assert r.status_code == 403
    assert not (vault / "evil.md").exists()


def test_lan_http_foreign_origin_with_matching_referer_is_blocked(bare_client) -> None:
    """Origin is authoritative when present — a matching Referer must not
    rescue a mismatched Origin."""
    c, vault = bare_client
    r = c.post(
        "/_mdshards/api/files",
        json={"path": "evil"},
        headers={
            "origin": "http://evil.example.com",
            "referer": "http://testserver/",
        },
    )
    assert r.status_code == 403
    assert not (vault / "evil.md").exists()


def test_bare_get_on_static_path_still_works(bare_client) -> None:
    """The block applies ONLY to /_mdshards/api/* and /_mdshards/ws/*. Typed-URL nav to / or to
    a vault page must still work without browser-fingerprint headers."""
    c, _ = bare_client
    assert c.get("/").status_code == 200


# ---- HTTP: sub-path mount (BASE_URL) ----
#
# Under a sub-path mount the ASGI spec says `path` INCLUDES `root_path`
# (Starlette strips it during routing), so a proxy following that contract
# forwards `/notes/_mdshards/api/tree` for BASE_URL=/notes. The guard must classify
# that as an API path — matching on the raw path would drop it into the
# loose static-path gate and let bare curl read (and mutate) the API.


@pytest.fixture
def prefixed_bare_client(vault, monkeypatch):
    """bare_client variant with BASE_URL=/notes — requests arrive with the
    sub-path prefix, per ASGI root_path semantics."""
    monkeypatch.setenv("BASE_URL", "/notes")
    from app import config

    config.get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c, vault
    config.get_settings.cache_clear()


def test_prefixed_bare_get_on_api_is_blocked(prefixed_bare_client) -> None:
    """Regression: `/notes/_mdshards/api/tree` with no browser fingerprint must 403 —
    the guard used to classify on the raw path, see the prefix, and wave the
    request through the static-path gate."""
    c, _ = prefixed_bare_client
    assert c.get("/notes/_mdshards/api/tree").status_code == 403


def test_prefixed_bare_post_on_api_is_blocked(prefixed_bare_client) -> None:
    c, vault = prefixed_bare_client
    r = c.post("/notes/_mdshards/api/files", json={"path": "curl_bypass"})
    assert r.status_code == 403
    assert not (vault / "curl_bypass.md").exists()


def test_prefixed_browser_get_on_api_passes(prefixed_bare_client) -> None:
    c, _ = prefixed_bare_client
    r = c.get("/notes/_mdshards/api/tree", headers={"sec-fetch-site": "same-origin"})
    assert r.status_code == 200


def test_prefixed_lan_http_get_with_referer_passes(prefixed_bare_client) -> None:
    """The two fallbacks compose: prefixed path + no Sec-Fetch-* (plain-HTTP
    LAN behind a prefix-preserving proxy like Traefik) + matching Referer."""
    c, _ = prefixed_bare_client
    r = c.get("/notes/_mdshards/api/tree", headers={"referer": "http://testserver/notes/"})
    assert r.status_code == 200


def test_unprefixed_api_still_classified_under_base_url(prefixed_bare_client) -> None:
    """A proxy that strips the prefix (or routes origin-rooted /_mdshards/api straight
    through) sends unprefixed paths; those must keep the strict gate too."""
    c, _ = prefixed_bare_client
    assert c.get("/_mdshards/api/tree").status_code == 403
    assert (
        c.get("/_mdshards/api/tree", headers={"sec-fetch-site": "same-origin"}).status_code == 200
    )


# ---- malformed / degenerate browser headers ----


def test_malformed_origin_is_blocked(client) -> None:
    """An Origin that urlparse can't digest must fail closed, not crash."""
    c, vault = client
    r = c.post(
        "/_mdshards/api/files",
        json={"path": "evil"},
        headers={"origin": "http://["},
    )
    assert r.status_code == 403
    assert not (vault / "evil.md").exists()


def test_null_origin_is_blocked(client) -> None:
    """`Origin: null` (sandboxed iframe / data: URL attacker) has no netloc
    and never matches our Host."""
    c, vault = client
    r = c.post("/_mdshards/api/files", json={"path": "evil"}, headers={"origin": "null"})
    assert r.status_code == 403
    assert not (vault / "evil.md").exists()


def test_cross_site_post_to_static_path_is_blocked(client) -> None:
    """The loose static-path gate still rejects state-changing requests that
    Sec-Fetch-Site explicitly tags as cross-site."""
    c, _ = client
    r = c.post("/whatever", headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403


# ---- WebSocket ----


def test_browser_ws_without_sec_fetch_site_is_allowed(bare_client) -> None:
    """Regression: real browsers omit ALL Sec-Fetch-* metadata on the WS
    opening handshake but always send `Origin`. Such a handshake (Origin
    present, no Sec-Fetch-Site) must be accepted — an earlier guard required
    Sec-Fetch-Site on /_mdshards/ws and rejected every real browser connection.

    Uses `bare_client` (no fixture-injected Sec-Fetch-Site) with only Origin
    set, to reproduce exactly what a browser sends."""
    c, vault = bare_client
    (vault / "x.md").write_text("hi")
    with c.websocket_connect("/_mdshards/ws/x", headers={"origin": "http://testserver"}) as ws:
        assert ws.receive_bytes()  # SYNC_STEP1


def test_bare_ws_is_blocked(bare_client) -> None:
    """A WS upgrade with no Origin (a raw non-browser caller) is closed
    before accept — browsers always send Origin on the handshake, so its
    absence marks the casual curl/script bypass. Only the bundle reaches
    /_mdshards/ws."""
    c, vault = bare_client
    (vault / "x.md").write_text("hi")
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with c.websocket_connect("/_mdshards/ws/x"):
            pass
    assert exc_info.value.code == 1008


def test_ws_same_origin_is_allowed(client) -> None:
    c, vault = client
    (vault / "x.md").write_text("hi")
    with c.websocket_connect("/_mdshards/ws/x", headers={"origin": "http://testserver"}) as ws:
        assert ws.receive_bytes()


def test_ws_cross_origin_is_blocked(client) -> None:
    c, vault = client
    (vault / "x.md").write_text("hi")
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with c.websocket_connect("/_mdshards/ws/x", headers={"origin": "https://evil.example.com"}):
            pass
    assert exc_info.value.code == 1008


def test_ws_sec_fetch_site_cross_site_is_blocked(client) -> None:
    c, vault = client
    (vault / "x.md").write_text("hi")
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with c.websocket_connect("/_mdshards/ws/x", headers={"sec-fetch-site": "cross-site"}):
            pass
    assert exc_info.value.code == 1008
