from pathlib import Path


def build_tree(vault_root: Path) -> dict:
    """Walk the vault and return a nested dict suitable for the frontend tree/switcher.

    Shape: ``{name, path, type: 'file'|'dir', children?}``.
    Hidden entries (starting with '.') are skipped. Files are listed before directories
    when sorted; both alphabetical within their group. Symlinks whose target
    resolves outside the vault root are skipped — the listing must never leak
    paths beyond the vault boundary.
    """
    if not vault_root.exists():
        return {"name": "", "path": "", "type": "dir", "children": []}
    return _walk(vault_root.resolve(), vault_root.resolve())


def _walk(node: Path, root: Path) -> dict:
    rel = "" if node == root else str(node.relative_to(root)).replace("\\", "/")
    if node.is_file():
        return {"name": node.name, "path": rel, "type": "file"}
    children = []
    for child in sorted(node.iterdir(), key=lambda p: (p.is_dir(), p.name)):
        if child.name.startswith("."):
            continue
        if _escapes_root(child, root):
            continue
        children.append(_walk(child, root))
    return {
        "name": node.name if node != root else "",
        "path": rel,
        "type": "dir",
        "children": children,
    }


def _escapes_root(child: Path, root: Path) -> bool:
    """True iff `child` either resolves outside `root`, is a broken symlink, or
    can't be resolved at all. The listing must never surface entries we can't
    safely classify."""
    try:
        resolved = child.resolve(strict=True)
    except OSError, RuntimeError:
        # Broken symlink, resolution loop, or vanished entry — skip.
        return True
    return not resolved.is_relative_to(root)
