import shutil
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ..config import get_settings
from ..files import delete_with_prune, move_with_prune
from ..vault import VaultPathError, resolve_asset

router = APIRouter(prefix="/api")


class MoveAssetRequest(BaseModel):
    src: str
    dst: str


@router.post("/assets", status_code=201)
async def upload_asset(
    file: Annotated[UploadFile, File()],
    path: Annotated[str, Form()],
    overwrite: Annotated[bool, Form()] = False,
) -> dict:
    """Upload a non-md asset at the given vault-relative path.

    Collisions are full-filename, filesystem-semantics matches: on a
    case-sensitive filesystem `foo.jpg`, `Foo.jpg`, and `foo.JPG` are three
    distinct files that never collide; on a case-insensitive one (macOS APFS)
    the `exists()` check naturally catches case-variant clashes too. An
    existing target is refused with 409 unless the caller explicitly sets
    `overwrite` — the frontend turns the 409 into an accept-or-rename prompt;
    nothing is silently replaced.
    """
    settings = get_settings()
    try:
        target = resolve_asset(path, settings.vault_dir)
    except VaultPathError as e:
        raise HTTPException(400, detail=str(e)) from e
    # `.md` is the CRDT layer's territory; the frontend dispatches md
    # uploads to `/api/files`. Refuse them here so a direct caller can't
    # sidestep the in-memory Doc and corrupt a note that's actively being
    # edited.
    if target.suffix.lower() == ".md":
        raise HTTPException(400, detail=".md paths are not assets; use /api/files")
    if target.exists() and not overwrite:
        raise HTTPException(409, detail="already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return {"path": path}


@router.post("/assets/move")
def move_asset(req: MoveAssetRequest) -> dict:
    """Rename/move a non-md asset from one vault path to another. No CRDT
    manager involvement — assets never enter the in-memory doc layer."""
    settings = get_settings()
    try:
        src_path = resolve_asset(req.src, settings.vault_dir)
        dst_path = resolve_asset(req.dst, settings.vault_dir)
    except VaultPathError as e:
        raise HTTPException(400, detail=str(e)) from e
    # Same reasoning as upload: don't let an asset move land on (or
    # originate from) a `.md` path, which belongs to the CRDT layer.
    if src_path.suffix.lower() == ".md" or dst_path.suffix.lower() == ".md":
        raise HTTPException(400, detail=".md paths are not assets; use /api/files/move")
    if src_path == dst_path:
        raise HTTPException(400, detail="source and destination are the same")
    if not src_path.exists():
        raise HTTPException(404, detail="source not found")
    if dst_path.exists():
        raise HTTPException(409, detail="destination already exists")
    move_with_prune(src_path, dst_path, settings.vault_dir)
    return {"from": req.src, "to": req.dst}


@router.delete("/assets/{asset_path:path}")
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
