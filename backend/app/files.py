import os
import tempfile
from pathlib import Path

from .vault import assert_inside

# Built-in fallback used to seed `<vault>/index.md` when no override is mounted.
DEFAULT_INDEX_TEMPLATE = Path(__file__).parent / "templates" / "index_placeholder.md"

# Optional user-supplied override for the index seed. Deliberately a FIXED,
# mountable path (drop a file here — or bind-mount one in a container — to
# customize the template) rather than an env var: an env-var path would be an
# arbitrary-file-read vector (point it at /etc/passwd and its contents land in
# the vault). When absent we fall back to the built-in default.
OVERRIDE_INDEX_TEMPLATE = Path("~/.mdshards/index.md").expanduser()


def resolve_index_template() -> Path:
    """Return the template to seed `<vault>/index.md` from: the mountable
    override at `~/.mdshards/index.md` if present, else the built-in default."""
    if OVERRIDE_INDEX_TEMPLATE.is_file():
        return OVERRIDE_INDEX_TEMPLATE
    return DEFAULT_INDEX_TEMPLATE


def read_md(path: Path, vault_root: Path) -> str:
    assert_inside(path, vault_root)
    return path.read_text(encoding="utf-8")


def write_md_atomic(path: Path, content: str, vault_root: Path) -> None:
    write_bytes_atomic(path, content.encode("utf-8"), vault_root)


def write_bytes_atomic(path: Path, data: bytes, containment_root: Path) -> None:
    """Atomic write. `containment_root` is the boundary the resolved `path`
    must stay inside — usually the vault, but the CRDT cache layer passes its
    own cache root so the same primitive can guard out-of-vault writes too."""
    assert_inside(path, containment_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def delete_with_prune(path: Path, vault_root: Path) -> None:
    """Delete `path`, then remove empty parent directories upward until a non-empty
    directory or the vault root is reached. The vault root itself is never removed."""
    path = assert_inside(path, vault_root)
    root = vault_root.resolve()
    if path.exists():
        path.unlink()
    _prune_empty_parents(path.parent, root)


def move_with_prune(src: Path, dst: Path, vault_root: Path) -> None:
    """Move `src` to `dst` inside the vault. Creates missing destination parent
    directories, then prunes any source parent directories left empty by the
    move — same "no empty dirs in the vault" invariant `delete_with_prune` keeps.
    The vault root itself is never removed.

    Both `src` and `dst` are containment-checked even when `dst.parent` doesn't
    exist yet — `assert_inside` walks up to the nearest existing ancestor,
    resolves THAT, then re-attaches the missing tail, so a symlink planted at
    a not-yet-created ancestor still gets caught."""
    src = assert_inside(src, vault_root)
    assert_inside(dst, vault_root)
    root = vault_root.resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Re-assert after mkdir in case anything raced the directory creation —
    # the resolved dst.parent may now follow a symlink that wasn't there when
    # we first checked.
    assert_inside(dst, vault_root)
    os.replace(src, dst)
    _prune_empty_parents(src.parent, root)


def _prune_empty_parents(parent: Path, root: Path) -> None:
    while parent != root and parent.is_relative_to(root):
        if any(parent.iterdir()):
            return
        parent.rmdir()
        parent = parent.parent


def ensure_index_exists(vault_root: Path) -> bool:
    """Materialize `<vault>/index.md` if missing, seeding it from the mountable
    override (`~/.mdshards/index.md`) when present, else the built-in default.
    Returns True if created, False if it already existed."""
    vault_root.mkdir(parents=True, exist_ok=True)
    index = vault_root / "index.md"
    if index.exists():
        return False
    template_path = resolve_index_template()
    write_md_atomic(index, template_path.read_text(encoding="utf-8"), vault_root)
    return True
