from functools import lru_cache

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from ..config import get_settings
from ..files import ensure_index_exists
from ..vault import VaultPathError, resolve_asset, resolve_md

router = APIRouter()

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


@router.get("/{full_path:path}")
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
    # markdown note with doc-id `X-without-.md`. Redirect the SPA to that
    # canonical URL — the next request lands in the md branch above.
    if stripped.endswith(".md"):
        canonical = stripped[:-3]
        return RedirectResponse(url=f"/{canonical}" if canonical else "/", status_code=302)

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
        return FileResponse(
            asset_path,
            headers={
                "Content-Security-Policy": "sandbox",
                "X-Content-Type-Options": "nosniff",
            },
        )
    raise HTTPException(404, detail="not found")
