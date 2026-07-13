from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import get_settings
from ..files import ensure_index_exists
from ..vault import VaultPathError, resolve_asset, resolve_md

router = APIRouter(prefix="/api")


ResourceType = Literal["md", "asset", "missing"]


class ResolveResponse(BaseModel):
    type: ResourceType
    """Canonical URL form for this resource, without a leading slash. Equal to
    the requested path when no redirect is needed. The SPA navigates to
    `/{canonical}` (with `replace: true`) whenever it differs from the
    pathname it asked about — that's how `.md` URLs whose md-doc-id form
    isn't on disk get rewritten to the extensionless form, and how typo'd
    URLs settle into a stable address before showing NotFound."""
    canonical: str = ""


def _resolve(stripped: str, vault_root: Path) -> ResolveResponse:
    """Apply the md-wins resolution rule, recursing into the canonical form
    when a `.md` URL doesn't have a matching `<X>.md.md` on disk."""
    if stripped in ("", "index"):
        # The root index regenerates from its template whenever it's missing
        # on disk — ALWAYS, not just in the deployment mode where the backend
        # serves the SPA shell. Resolve is the one call every navigation to
        # `/` makes regardless of who served the shell (dev server, vite
        # preview, nginx, static host), so the guarantee lives here too.
        ensure_index_exists(vault_root)
        return ResolveResponse(type="md", canonical="")

    try:
        md_path = resolve_md(stripped, vault_root)
    except VaultPathError as e:
        raise HTTPException(400, detail=str(e)) from e
    if md_path.exists():
        return ResolveResponse(type="md", canonical=stripped)

    if stripped.endswith(".md"):
        # The literal `<vault>/X.md` (if it exists) is itself a markdown
        # note with doc-id `X-without-.md`. Recurse on the canonical form
        # so the response carries the right URL for the SPA to redirect to.
        return _resolve(stripped[:-3], vault_root)

    try:
        asset_path = resolve_asset(stripped, vault_root)
    except VaultPathError:
        return ResolveResponse(type="missing", canonical=stripped)
    if asset_path.exists() and asset_path.is_file():
        return ResolveResponse(type="asset", canonical=stripped)
    return ResolveResponse(type="missing", canonical=stripped)


@router.get("/resolve")
@router.get("/resolve/{url_path:path}")
def resolve(url_path: str = "") -> ResolveResponse:
    """Tell the SPA what kind of resource lives at a URL path and what the
    canonical URL for it is. Called by `useResolve` on every navigation; the
    canonical form drives client-side `replace`-redirects (`/foo.md` →
    `/foo` when `vault/foo.md` is itself an md note). Resolution order is
    file-existence based:

      1. Root (`/` or `/index`) is always md.
      2. `<vault>/<path>.md` exists → md, canonical = `<path>`.
      3. `<path>` ends in `.md` and `<vault>/<path>` exists → recurse with
         the canonical form (strip the trailing `.md`).
      4. `<vault>/<path>` exists as a regular file → asset.
      5. Otherwise → missing (canonical = `<path>` itself).

    Returns 200 in every case — "missing" is a valid resolution. Invalid
    path syntax (traversal, backslash, null byte) returns 400 since the SPA
    can't navigate to those URLs anyway. Spaces are legal and resolve
    normally.
    """
    settings = get_settings()
    return _resolve(url_path.strip("/"), settings.vault_dir)
