from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from ..config import get_settings
from ..files import delete_with_prune, move_with_prune, write_md_atomic
from ..vault import VaultPathError, resolve_md

router = APIRouter(prefix="/api")


def _reject_attachments_write(target: Path, vault_dir: Path) -> None:
    """DEMO: the `attachments/` directory holds ONLY the seeded demo assets.
    Users may not create or move notes into it — reads/serving stay open, so
    the seeded assets still render. (Serving lives under the catch-all, not
    here.) Raises 403 when `target` resolves inside `<vault>/attachments/`."""
    attachments = (vault_dir / "attachments").resolve()
    if target == attachments or target.is_relative_to(attachments):
        raise HTTPException(403, detail="the attachments/ directory is read-only")


class CreateFileRequest(BaseModel):
    path: str
    # Optional body content. Used by the upload flow when the source is a .md
    # file — the bytes ride in the same request rather than via a separate
    # multipart upload. Defaults to empty so quick-switcher creates still get
    # a blank note.
    content: str = ""
    # Explicit acceptance of replacing an existing note. Only the upload
    # flow sets this (after its accept-or-rename prompt); the quick-switcher
    # never does — Shift-Enter can never overwrite an existing file.
    overwrite: bool = False


class MoveFileRequest(BaseModel):
    src: str
    dst: str


@router.post(
    "/files",
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "invalid vault path"},
        409: {"description": "file already exists (and overwrite not set)"},
    },
)
def create_file(req: CreateFileRequest) -> dict:
    settings = get_settings()
    try:
        target = resolve_md(req.path, settings.vault_dir)
    except VaultPathError as e:
        raise HTTPException(400, detail=str(e)) from e
    _reject_attachments_write(target, settings.vault_dir)
    if target.exists() and not req.overwrite:
        raise HTTPException(409, detail="file already exists")
    # An overwrite of a note that's actively open rides the same path as any
    # external writer: the atomic write lands on disk and the vault watcher
    # ghost-merges it into the live Doc.
    write_md_atomic(target, req.content, settings.vault_dir)
    return {"path": req.path}


@router.post(
    "/files/move",
    responses={
        400: {"description": "invalid path, or source and destination are the same"},
        403: {"description": "index.md cannot be renamed, nor renamed onto"},
        404: {"description": "source not found"},
        409: {"description": "destination already exists"},
    },
)
async def move_file(req: MoveFileRequest, request: Request) -> dict:
    """Rename a note from one vault path to another. Kicks attached clients,
    moves the .md and the CRDT cache, and prunes any source parents the move
    leaves empty."""
    settings = get_settings()
    try:
        src_path = resolve_md(req.src, settings.vault_dir)
        dst_path = resolve_md(req.dst, settings.vault_dir)
    except VaultPathError as e:
        raise HTTPException(400, detail=str(e)) from e
    if src_path == dst_path:
        raise HTTPException(400, detail="source and destination are the same")
    _reject_attachments_write(dst_path, settings.vault_dir)
    index_md = (settings.vault_dir / "index.md").resolve()
    if src_path == index_md:
        raise HTTPException(403, detail="index.md cannot be renamed")
    if dst_path == index_md:
        raise HTTPException(403, detail="cannot rename to index.md")
    if not src_path.exists():
        raise HTTPException(404, detail="source not found")
    if dst_path.exists():
        raise HTTPException(409, detail="destination already exists")
    # Order matters (same reasoning as delete): kick + move cache before the
    # disk move, so a racing flush can't recreate the source.
    manager = getattr(request.app.state, "doc_manager", None)
    if manager is not None:
        await manager.rename(req.src, req.dst)
    move_with_prune(src_path, dst_path, settings.vault_dir)
    return {"from": req.src, "to": req.dst}


@router.delete(
    "/files/{file_path:path}",
    responses={
        400: {"description": "invalid vault path"},
        403: {"description": "index.md cannot be deleted"},
        404: {"description": "not found"},
    },
)
async def delete_file(file_path: str, request: Request) -> dict:
    settings = get_settings()
    try:
        target = resolve_md(file_path, settings.vault_dir)
    except VaultPathError as e:
        raise HTTPException(400, detail=str(e)) from e
    index_md = (settings.vault_dir / "index.md").resolve()
    if target == index_md:
        raise HTTPException(403, detail="index.md cannot be deleted")
    if not target.exists():
        raise HTTPException(404, detail="not found")
    # Order matters: kick first so any connected editor stops pushing edits
    # into the Doc (which would resurrect the file on the next flush) BEFORE
    # we unlink the disk file and clear the cache.
    manager = getattr(request.app.state, "doc_manager", None)
    if manager is not None:
        await manager.kick(file_path)
    delete_with_prune(target, settings.vault_dir)
    if manager is not None:
        manager.purge(file_path)
    return {"deleted": file_path}
