"""Origin / Sec-Fetch-Site guards for CSRF + WebSocket-hijack defense, and
for blocking non-browser callers on the API surface.

There is no auth (see CLAUDE.md). The threats this middleware addresses are:

1. Browser-driven cross-origin attacks. A page on evil.com that does
   `fetch('https://notes.example.com/wiki/api/assets', …)` or opens a
   `new WebSocket('wss://notes.example.com/wiki/ws/index')`. The proxy
   forwards both legitimately; only the backend can tell them apart from
   same-origin calls by inspecting the browser-set `Origin` and
   `Sec-Fetch-Site` headers.

2. Non-browser callers (curl, scripts, server-to-server) hitting `/api/*`
   or `/ws/*` and bypassing the prebuilt frontend. Browsers send
   `Sec-Fetch-Site` on every ordinary request; curl by default sends
   nothing. So on `/api/*` we REQUIRE `Sec-Fetch-Site` to be present and in
   the same-origin / same-site / none set. This is not crypto-strong
   (`curl -H "Sec-Fetch-Site: same-origin"` still gets through), but it
   stops the casual bypass and matches the "only the loaded bundle drives
   the API" intent.

   WebSocket handshakes are the exception: browsers do NOT emit any
   Sec-Fetch-* metadata on the WS opening handshake, so requiring it there
   would reject every real browser. Browsers do, however, always send
   `Origin` on a WS handshake — so `/ws/*` uses Origin-presence as the
   equivalent casual-bypass gate.

Static paths (`/`, `/assets/*`, `/favicon.svg`,
`<vault-asset>` URLs) still allow direct navigation — typed URLs and
bookmarks must keep working — so they keep the looser gate: safe methods
pass unconditionally, only state-changing requests check origin.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from urllib.parse import urlparse

from starlette.types import ASGIApp, Receive, Scope, Send

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# `Sec-Fetch-Site` values modern browsers send when the request is NOT from
# a foreign origin. `none` covers direct navigation (typed URL, bookmark).
SAFE_SEC_FETCH_SITE = {"same-origin", "same-site", "none"}


def _is_api_or_ws(path: str) -> bool:
    """True if `path` targets the REST API or WebSocket endpoints — the
    surfaces the prebuilt frontend bundle is the only legitimate client of.
    Used to apply the stricter Sec-Fetch-Site presence rule."""
    return path in ("/api", "/ws") or path.startswith("/api/") or path.startswith("/ws/")


def _header(headers: Iterable[tuple[bytes, bytes]], name: bytes) -> str | None:
    needle = name.lower()
    for k, v in headers:
        if k.lower() == needle:
            return v.decode("latin-1")
    return None


def is_request_allowed(scope: Scope) -> bool:
    """Decide whether a single ASGI scope (HTTP or WebSocket) is from a
    permitted origin. Returns True for non-browser callers (no `Origin`
    header) — see module docstring."""
    headers = scope.get("headers") or []
    origin = _header(headers, b"origin")
    site = _header(headers, b"sec-fetch-site")

    # Modern browsers always send `Sec-Fetch-Site`. If it explicitly tags
    # the request as cross-site we can short-circuit without needing to
    # know our own origin.
    if site is not None and site not in SAFE_SEC_FETCH_SITE:
        return False

    if origin is None:
        return True

    # Match the `Origin` against the request's own `Host` header. We
    # deliberately don't compare schemes here because a reverse proxy may
    # terminate TLS, so the backend sees `http` while the browser sees
    # `https`. This is LAN-first by design — whatever host the browser used
    # to reach us is the origin we accept; there is no operator-declared
    # canonical hostname to configure.
    host = _header(headers, b"host")
    if not host:
        # Can't establish what our own origin is. Fall back to the
        # Sec-Fetch-Site verdict above (which already passed).
        return True
    try:
        origin_netloc = urlparse(origin).netloc.lower()
    except ValueError:
        return False
    return origin_netloc == host.lower()


async def _reject_http(send: Send) -> None:
    body = json.dumps({"detail": "cross-origin request blocked"}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _reject_websocket(receive: Receive, send: Send) -> None:
    # Drain the initial `websocket.connect` event, then close before ever
    # accepting. uvicorn translates this into an HTTP 403 on the upgrade,
    # so the browser's WebSocket constructor fires `error` and the
    # connection never opens.
    event = await receive()
    if event.get("type") != "websocket.connect":
        return
    await send({"type": "websocket.close", "code": 1008})


class OriginGuard:
    """ASGI middleware that blocks state-changing HTTP requests and any
    WebSocket upgrade from a foreign origin. Safe HTTP methods
    (GET/HEAD/OPTIONS) pass through unconditionally.

    Lives at the ASGI layer (not as a FastAPI dependency) so it catches
    WebSocket scopes too — `Depends(...)` doesn't run for `@router.websocket`.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]
        if kind == "http":
            await self._handle_http(scope, receive, send)
        elif kind == "websocket":
            await self._handle_websocket(scope, receive, send)
        else:
            # `lifespan` and anything else — pass through unchanged.
            await self.app(scope, receive, send)

    async def _handle_http(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        # /api/* and /ws/* are the surfaces the bundle calls. Require a
        # browser-style `Sec-Fetch-Site` on every method, including GET —
        # that's what blocks bare curl / scripted callers.
        if _is_api_or_ws(path):
            headers = scope.get("headers") or []
            site = _header(headers, b"sec-fetch-site")
            if site is None or site not in SAFE_SEC_FETCH_SITE:
                await _reject_http(send)
                return
            if not is_request_allowed(scope):
                await _reject_http(send)
                return
            await self.app(scope, receive, send)
            return
        # Static paths: keep the looser gate so typed-URL nav works.
        if method in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        if not is_request_allowed(scope):
            await _reject_http(send)
            return
        await self.app(scope, receive, send)

    async def _handle_websocket(self, scope: Scope, receive: Receive, send: Send) -> None:
        # All WebSocket endpoints live under /ws. Unlike the HTTP /api branch
        # we do NOT require `Sec-Fetch-Site`: browsers omit ALL Sec-Fetch-*
        # metadata on the WebSocket opening handshake, so requiring it would
        # reject every legitimate browser connection. Browsers DO always send
        # `Origin` on the WS handshake, so we use Origin-presence as the
        # browser fingerprint that blocks bare non-browser callers (curl sends
        # none) — the same casual-bypass gate the /api branch gets from
        # Sec-Fetch-Site. is_request_allowed then validates that Origin against
        # the `Host` header, blocking the cross-origin hijack case.
        headers = scope.get("headers") or []
        if _header(headers, b"origin") is None:
            await _reject_websocket(receive, send)
            return
        if not is_request_allowed(scope):
            await _reject_websocket(receive, send)
            return
        await self.app(scope, receive, send)
