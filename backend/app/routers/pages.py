from functools import lru_cache

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from ..config import get_settings
from ..files import ensure_index_exists
from ..vault import VaultPathError, resolve_asset, resolve_md

router = APIRouter()

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


@lru_cache(maxsize=1)
def _spa_shell() -> str:
    """Return the SPA shell HTML. When the frontend bundle is present (the
    single-container image; `settings.static_dir` resolves), this is the real
    `index.html` Vite emits — the one with hashed `<script>` and `<link>` tags
    for the built bundle. In dev (no bundle), the bare placeholder is enough
    because Vite injects its own dev bootstrap."""
    static_dir = get_settings().static_dir
    if static_dir is not None:
        index_html = static_dir / "index.html"
        if index_html.is_file():
            return index_html.read_text(encoding="utf-8")
    return _PLACEHOLDER_SHELL


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

    # `/index` is the doc-id form of the home note; canonicalise to `/`.
    if stripped == "index":
        return RedirectResponse(url="/", status_code=302)

    if stripped == "":
        ensure_index_exists(settings.vault_dir)
        return HTMLResponse(_spa_shell())

    try:
        md_path = resolve_md(stripped, settings.vault_dir)
    except VaultPathError as e:
        raise HTTPException(400, detail=str(e)) from e

    if md_path.exists():
        return HTMLResponse(_spa_shell())

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
        return HTMLResponse(_spa_shell())

    try:
        asset_path = resolve_asset(stripped, settings.vault_dir)
    except VaultPathError:
        asset_path = None

    is_doc_nav = request.headers.get("sec-fetch-dest") == "document"
    asset_exists = asset_path is not None and asset_path.exists() and asset_path.is_file()

    if is_doc_nav:
        return HTMLResponse(_spa_shell())
    if asset_exists:
        # `Content-Security-Policy: sandbox` neutralizes scripts/forms in the
        # response itself, so a vault `.html` (or `.svg` opened top-level on a
        # browser that doesn't send Sec-Fetch-Dest) can't run same-origin JS.
        # `nosniff` stops content-type sniffing from upgrading a misdeclared
        # asset back to text/html. The frontend's iframe also sets
        # `sandbox="allow-same-origin"` — these are belt-and-suspenders.
        #
        # `Cache-Control: no-cache` forces the browser to revalidate before
        # reusing a cached copy. Vault assets are mutable — deleted, replaced
        # at the same path (upload overwrites), or rewritten by an external
        # tool (Syncthing/Obsidian) — and Starlette's FileResponse sets an
        # etag/last-modified but does no conditional-GET handling, so without
        # this the browser would heuristically cache and keep serving a stale
        # (or deleted) asset. "no-cache" still allows storage, just not reuse
        # without a round-trip, so the fetch after a delete correctly 404s.
        headers = {
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-cache",
        }
        # `CSP: sandbox` only where it buys protection: types that can
        # execute script in the SPA's origin (the vault takes external
        # writes, so a synced .html/.svg is the XSS vector). Everything else
        # gets browser-default handling — a blanket sandbox would block the
        # PDF viewer plugin outright and silently swallow the download
        # fallback for non-renderable types (blank page instead of a save).
        # `nosniff` (always sent) pins the declared content-type, so a
        # misnamed file can't be sniffed back up to text/html. Mirrors
        # SCRIPTABLE_EXTS in the frontend's lib/asset-kind.ts.
        if asset_path.suffix.lower() in _SCRIPTABLE_SUFFIXES:
            headers["Content-Security-Policy"] = "sandbox"
        return FileResponse(asset_path, headers=headers)
    raise HTTPException(404, detail="not found")
