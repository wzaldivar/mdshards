from pathlib import Path, PurePosixPath


class VaultPathError(ValueError):
    """A URL path that does not resolve safely into the vault."""


def _validate(url_path: str) -> str:
    if url_path is None:
        raise VaultPathError("missing path")
    if "\x00" in url_path:
        raise VaultPathError("null byte in path")
    if " " in url_path:
        raise VaultPathError("spaces not allowed in vault paths")
    stripped = url_path.lstrip("/")
    if not stripped:
        return ""
    parts = PurePosixPath(stripped).parts
    for p in parts:
        if p in ("", ".", ".."):
            raise VaultPathError(f"illegal path segment: {p!r}")
        if "\\" in p:
            raise VaultPathError("backslash in path segment")
    return "/".join(parts)


def assert_inside(path: Path, root: Path) -> Path:
    """Defense-in-depth containment check. Resolves both `path` and `root` and
    raises `VaultPathError` if the resolved path is not under the resolved
    root. Returns the resolved path on success.

    Use this at the boundary of any function that writes/reads/deletes/moves a
    file when the caller already *should* have validated — the assertion turns
    "the caller promised" into "we checked." Call sites that derive paths from
    a vault root (resolve_md / resolve_asset) get this for free; primitives in
    files.py and docs.py call it directly so they can't be misused by a future
    refactor."""
    resolved_root = root.resolve()
    resolved = path.resolve() if path.exists() else _resolve_nonexistent(path)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as e:
        raise VaultPathError("path escapes the containment root") from e
    return resolved


def _resolve_nonexistent(path: Path) -> Path:
    """Resolve a path whose final component(s) may not exist yet. Walks up to
    the nearest existing ancestor, resolves THAT (following any symlinks in
    the existing prefix), then re-attaches the missing tail. This is what lets
    `assert_inside` catch symlinks planted at not-yet-created parent dirs."""
    missing: list[str] = []
    cur = path
    while not cur.exists():
        if cur.parent == cur:
            return path.resolve(strict=False)
        missing.append(cur.name)
        cur = cur.parent
    resolved_base = cur.resolve()
    for name in reversed(missing):
        resolved_base = resolved_base / name
    return resolved_base


def _safe_join(vault_root: Path, candidate: Path) -> Path:
    try:
        return assert_inside(candidate, vault_root)
    except VaultPathError as e:
        raise VaultPathError("path escapes the vault root") from e


def resolve_md(url_path: str, vault_root: Path) -> Path:
    """Return the absolute on-disk `.md` path for a URL path. The file may not exist."""
    rel = _validate(url_path)
    return _safe_join(vault_root, vault_root / ("index.md" if rel == "" else f"{rel}.md"))


def resolve_asset(url_path: str, vault_root: Path) -> Path:
    """Return the absolute on-disk path for a non-md asset URL. The file may not exist."""
    rel = _validate(url_path)
    if rel == "" or not Path(rel).suffix:
        raise VaultPathError("asset path requires an extension")
    return _safe_join(vault_root, vault_root / rel)
