import html
import re
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from ..config import get_settings
from ..files import ensure_index_exists
from ..vault import VaultPathError, resolve_asset, resolve_md

router = APIRouter()

# Root-rooted src/href attributes in the Vite shell (hashed bundle files,
# favicon). `(?!/)` spares protocol-relative `//host` URLs; absolute
# `https://` ones never match the leading `"/`.
_SRC_HREF_RE = re.compile(r'\b(src|href)="/(?!/)')

# Suffixes that can execute script when served same-origin — the only ones
# that need `CSP: sandbox`. Keep in lockstep with SCRIPTABLE_EXTS in the
# frontend's lib/asset-kind.ts.
_SCRIPTABLE_SUFFIXES = {
    ".html",
    ".htm",
    ".xhtml",
    ".xht",
    ".shtml",
    ".xml",
    ".svg",
    ".mht",
    ".mhtml",
}

_PLACEHOLDER_SHELL = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    "<title>mdshards</title></head>"
    '<body><div id="app"></div></body></html>'
)


def asset_response(asset_path: Path) -> FileResponse:
    """Serve vault-asset bytes with the standard protection headers. Shared
    by the catch-all's sub-resource branch and `/api/embed` (assets router).

    `Content-Security-Policy: sandbox` neutralizes scripts/forms in the
    response itself, so a vault `.html` (or `.svg` opened top-level on a
    browser that doesn't send Sec-Fetch-Dest) can't run same-origin JS.
    `nosniff` stops content-type sniffing from upgrading a misdeclared
    asset back to text/html. The frontend's iframe also sets
    `sandbox="allow-same-origin"` — these are belt-and-suspenders.

    `Cache-Control: no-cache` forces the browser to revalidate before
    reusing a cached copy. Vault assets are mutable — deleted, replaced
    at the same path (upload overwrites), or rewritten by an external
    tool (Syncthing/Obsidian) — and Starlette's FileResponse sets an
    etag/last-modified but does no conditional-GET handling, so without
    this the browser would heuristically cache and keep serving a stale
    (or deleted) asset. "no-cache" still allows storage, just not reuse
    without a round-trip, so the fetch after a delete correctly 404s.

    `CSP: sandbox` only where it buys protection: types that can execute
    script in the SPA's origin (the vault takes external writes, so a
    synced .html/.svg is the XSS vector). Everything else gets
    browser-default handling — a blanket sandbox would block the PDF
    viewer plugin outright and silently swallow the download fallback for
    non-renderable types (blank page instead of a save). Mirrors
    SCRIPTABLE_EXTS in the frontend's lib/asset-kind.ts."""
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-cache",
    }
    if asset_path.suffix.lower() in _SCRIPTABLE_SUFFIXES:
        headers["Content-Security-Policy"] = "sandbox"
    return FileResponse(asset_path, headers=headers)


def _prefix_shell(shell: str, base_url: str) -> str:
    """Sub-path containment, serve-time half. When BASE_URL is set, rewrite
    the shell's root-rooted `src`/`href` attributes (the hashed bundle files,
    favicon) to live under the prefix, and inject a
    `<meta name="mdshards-home-path">` tag the bundle reads before its first
    fetch (frontend `lib/backend.ts`) so every runtime URL — /api, /ws,
    vault assets — is prefixed too. This is SERVE-time, not build-time: the
    same `dist/` still deploys at any prefix without a rebuild."""
    if not base_url:
        return shell
    prefix = html.escape(base_url, quote=True)
    rewritten = _SRC_HREF_RE.sub(lambda m: f'{m.group(1)}="{prefix}/', shell)
    meta = f'<meta name="mdshards-home-path" content="{prefix}">'
    return rewritten.replace("<head>", "<head>" + meta, 1)


@lru_cache(maxsize=4)
def _spa_shell(static_dir: Path | None, base_url: str) -> str:
    """Return the SPA shell HTML. When the frontend bundle is present (the
    single-container image; `settings.static_dir` resolves), this is the real
    `index.html` Vite emits — the one with hashed `<script>` and `<link>` tags
    for the built bundle. In dev (no bundle), the bare placeholder is enough
    because Vite injects its own dev bootstrap. Cached per (static_dir,
    base_url) — both are process-constant in production; the key matters for
    the test suite, which builds apps with different settings."""
    shell = _PLACEHOLDER_SHELL
    if static_dir is not None:
        index_html = static_dir / "index.html"
        if index_html.is_file():
            shell = index_html.read_text(encoding="utf-8")
    return _prefix_shell(shell, base_url)


def _shell_response() -> HTMLResponse:
    settings = get_settings()
    return HTMLResponse(_spa_shell(settings.static_dir, settings.base_url))


@router.get(
    "/{full_path:path}",
    responses={
        400: {"description": "invalid vault path"},
        404: {"description": "asset sub-resource not found"},
    },
)
def page_or_asset(full_path: str, request: Request):
    """Catch-all that hands the browser one of:
      - the SPA shell (markdown, missing, asset doc-nav, `.md` URLs), or
      - the raw asset bytes (asset sub-resource fetches).

    Markdown vs. asset is disambiguated by file existence — `<path>.md` wins
    if it exists, then literal `<path>` is tried as an asset. URLs ending in
    `.md` are accepted; if `<X.md>.md` (the doc-id form) doesn't exist on
    disk, the URL canonicalizes by stripping the trailing `.md`. The SPA
    handles that final redirect via the `canonical` field on `/api/resolve`.
    """
    settings = get_settings()

    stripped = full_path.strip("/")

    # `/index` is the doc-id form of the home note; canonicalise to `/`
    # (prefixed under a sub-path mount — a bare "/" would drop BASE_URL).
    if stripped == "index":
        return RedirectResponse(url=f"{settings.base_url}/", status_code=302)

    if stripped == "":
        ensure_index_exists(settings.vault_dir)
        return _shell_response()

    try:
        md_path = resolve_md(stripped, settings.vault_dir)
    except VaultPathError as e:
        raise HTTPException(400, detail=str(e)) from e

    if md_path.exists():
        return _shell_response()

    # `.md` URL whose doc-id form has no `<vault>/X.md.md` on disk. Per the
    # md-wins rule, the literal `<vault>/X.md` (if it exists) is itself a
    # markdown note with doc-id `X-without-.md`. Hand the browser the SPA
    # shell and let it canonicalize to `/X` client-side via `/api/resolve`'s
    # `canonical` field (`useResolve` does a `replace`-navigate). Doing this
    # in the SPA rather than a server 302 keeps user-controlled request data
    # out of any redirect `Location`. The branch itself is still required so
    # a `.md` URL never falls through to asset resolution below — that would
    # serve the raw bytes of a literal `X.md` note and violate md-wins.
    if stripped.endswith(".md"):
        return _shell_response()

    try:
        asset_path = resolve_asset(stripped, settings.vault_dir)
    except VaultPathError:
        asset_path = None

    dest = request.headers.get("sec-fetch-dest")
    asset_exists = asset_path is not None and asset_path.exists() and asset_path.is_file()

    if dest == "document":
        return _shell_response()
    if asset_exists:
        return asset_response(asset_path)
    # No Fetch Metadata at all — browsers only send `Sec-Fetch-*` to
    # potentially trustworthy origins (https / localhost), so a plain-HTTP
    # LAN browser lands here for every missing path. A top-level navigation
    # advertises `text/html` in `Accept`; img/fetch sub-resources don't.
    # Serve the shell so the SPA's NotFound view renders instead of a bare
    # 404 body. Existing assets were already handled above, so iframe and
    # image fetches of real files still get bytes.
    if dest is None and "text/html" in request.headers.get("accept", ""):
        return _shell_response()
    raise HTTPException(404, detail="not found")
