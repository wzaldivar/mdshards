from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import get_settings
from ..files import delete_with_prune, move_with_prune
from ..vault import VaultPathError, resolve_asset, resolve_md
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


class MoveAssetRequest(BaseModel):
    src: str
    dst: str


# NOTE: the asset upload endpoint (POST /api/assets) is intentionally removed on
# the demo branch — this is a public, no-auth deployment, so accepting arbitrary
# uploaded bytes is an abuse vector. The frontend keeps the Cmd-U affordance
# (it opens the OS file picker) but sends nothing. Asset move/delete/embed and
# note creation (POST /api/files) remain.


@router.post(
    "/assets/move",
    responses={
        400: {"description": "invalid path, a lowercase .md source, or src == dst"},
        404: {"description": "source not found"},
        409: {"description": "destination already exists"},
    },
)
def move_asset(req: MoveAssetRequest) -> dict:
    """Rename/move a non-md asset from one vault path to another. No CRDT
    manager involvement — assets never enter the in-memory doc layer.

    A destination ending in `.md` (any casing) CONVERTS the asset into a
    note: the bytes move to the canonical lowercase `.md` path and the file
    becomes doc-id `<dst-without-extension>`. Whether the content is valid
    markdown is the user's problem — the frontend confirms before sending.
    This is also the sanctioned escape hatch for a stray `foo.MD` created
    directly on the filesystem (an asset under the canonical rules): rename
    it to `foo.md` and it becomes a proper note. Only a true lowercase
    `.md` SOURCE stays forbidden here — that's a live note and belongs to
    /api/files/move.
    """
    settings = get_settings()
    dst_is_md = req.dst.strip()[-3:].lower() == ".md"
    try:
        src_path = resolve_asset(req.src, settings.vault_dir)
        if dst_is_md:
            doc_id = req.dst.strip().rstrip("/")[:-3]
            dst_path = resolve_md(doc_id, settings.vault_dir)
        else:
            dst_path = resolve_asset(req.dst, settings.vault_dir)
    except VaultPathError as e:
        raise HTTPException(400, detail=str(e)) from e
    if src_path.suffix == ".md":
        raise HTTPException(400, detail="lowercase .md is a note; use /api/files/move")
    if src_path == dst_path:
        raise HTTPException(400, detail="source and destination are the same")
    if not src_path.exists():
        raise HTTPException(404, detail="source not found")
    # On a case-insensitive filesystem a case-only rename (foo.MD → foo.md)
    # sees its own inode at the destination — that's not a collision.
    if dst_path.exists() and not dst_path.samefile(src_path):
        raise HTTPException(409, detail="destination already exists")
    move_with_prune(src_path, dst_path, settings.vault_dir)
    if dst_is_md:
        return {"from": req.src, "to": doc_id, "converted": True}
    return {"from": req.src, "to": req.dst, "converted": False}


@router.delete(
    "/assets/{asset_path:path}",
    responses={
        400: {"description": "invalid vault path"},
        404: {"description": "not found"},
    },
)
def delete_asset(asset_path: str) -> dict:
    settings = get_settings()
    try:
        target = resolve_asset(asset_path, settings.vault_dir)
    except VaultPathError as e:
        raise HTTPException(400, detail=str(e)) from e
    if not target.exists():
        raise HTTPException(404, detail="not found")
    delete_with_prune(target, settings.vault_dir)
    return {"deleted": asset_path}
