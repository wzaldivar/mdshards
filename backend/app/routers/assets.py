from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..config import get_settings
from ..vault import VaultPathError, resolve_asset
from .pages import asset_response

router = APIRouter(prefix="/api")


def _walk_segments(base: list[str], target: str) -> str | None:
    """Resolve `target` against `base` purely lexically. Returns the
    vault-relative path, or None when a `..` steps past the vault root —
    an escaping candidate simply doesn't exist in our universe."""
    parts = list(base)
    for seg in target.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(seg)
    return "/".join(parts) if parts else None


@router.get(
    "/embed",
    responses={
        400: {"description": "invalid target (traversal, .md, or empty)"},
        404: {"description": "target not found at either candidate location"},
    },
)
def embed_asset(note: str, target: str) -> FileResponse:
    """Serve the asset a wikilink image embed (`![[target]]` in `note`)
    points at. ONE request from the browser; the server resolves the target
    against two candidate locations with fixed priority — ADJACENT to the
    embedding note first, vault root second (adjacent overshadows root when
    both exist). Two stat() calls at request time: always fresh, no client
    fallback round-trip, no 404 noise for root-resolved embeds.

    `..` segments inside the target are allowed as long as the resolved
    path stays inside the vault (`resolve_asset` enforces the boundary);
    a candidate that escapes is simply skipped. `.md` targets are refused —
    notes belong to the CRDT layer, never to byte serving."""
    target = target.strip()
    if not target:
        raise HTTPException(400, detail="empty target")
    if target.lower().endswith(".md"):
        raise HTTPException(400, detail=".md targets are notes, not embeddable assets")
    note_dir = note.rsplit("/", 1)[0] if "/" in note else ""
    base = [p for p in note_dir.split("/") if p] if note_dir else []
    # Lexical walk mirroring the frontend's resolveAssetUrl: `..` pops a
    # level, popping past the vault root marks the candidate as escaping
    # (dropped, never capped at `/`). The vault layer itself refuses `..`
    # segments wholesale, so normalization must happen here.
    candidates = []
    for walked in (_walk_segments(base, target), _walk_segments([], target)):
        if walked is not None and walked not in candidates:
            candidates.append(walked)
    settings = get_settings()
    resolved_any = False
    for rel in candidates:
        try:
            path = resolve_asset(rel, settings.vault_dir)
        except VaultPathError:
            continue
        resolved_any = True
        if path.exists() and path.is_file():
            return asset_response(path)
    if not resolved_any:
        raise HTTPException(400, detail="invalid target")
    raise HTTPException(404, detail="not found")


# NOTE: assets are READ-ONLY on the demo branch. Every asset MUTATION endpoint
# is intentionally removed — POST /api/assets (upload), POST /api/assets/move
# (rename/convert), and DELETE /api/assets/{path}. This is a public, no-auth
# deployment, so letting anyone add, rename, or delete vault assets is an abuse
# vector. Assets stay served read-only (GET /api/embed above + the static asset
# routes); note create/rename/delete via /api/files is unaffected. This is a
# server-only lockdown: the frontend still shows the upload/rename/delete
# affordances, which simply fail against the now-absent endpoints.
