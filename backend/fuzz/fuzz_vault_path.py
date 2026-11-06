"""Fuzz the path-traversal boundary (`app/vault.py`).

Every vault URL goes through `_validate` and then `resolve_md` /
`resolve_asset`. The contract: either `VaultPathError` is raised, or the
returned path is inside the vault root — `..` segments, backslashes, null
bytes, the reserved `_mdshards` segment and symlinks planted inside the vault
(pointing out of it, dangling or not) must never yield an outside path.

Run locally (Linux, from backend/):  PYTHONPATH=. python fuzz/fuzz_vault_path.py
"""

import os
import sys
import tempfile
from pathlib import Path

import atheris

with atheris.instrument_imports():
    from app.vault import VaultPathError, _validate, resolve_asset, resolve_md


def _make_vault() -> Path:
    """A throwaway vault with the shapes that make containment interesting:
    nested dirs, a symlink escaping the root, a dangling escaping symlink and
    a benign in-vault symlink."""
    base = Path(tempfile.mkdtemp(prefix="mdshards-fuzz-"))
    vault = base / "vault"
    outside = base / "outside"
    (vault / "notes" / "deep").mkdir(parents=True)
    outside.mkdir()
    (vault / "index.md").write_text("# index\n")
    (vault / "notes" / "a.md").write_text("a\n")
    (outside / "secret.md").write_text("secret\n")
    os.symlink(outside, vault / "escape")
    os.symlink(outside / "not-yet", vault / "notes" / "dangle")
    os.symlink(vault / "notes", vault / "alias")
    return vault


VAULT = _make_vault()
ROOT = VAULT.resolve()


def _check_validated(rel: str) -> None:
    if rel == "":
        return
    if rel.startswith("/") or "\x00" in rel or "\\" in rel:
        raise AssertionError(f"_validate let through {rel!r}")
    parts = rel.split("/")
    if parts[0] == "_mdshards" or any(p in ("", ".", "..") for p in parts):
        raise AssertionError(f"_validate let through {rel!r}")


def TestOneInput(data: bytes) -> None:
    url_path = atheris.FuzzedDataProvider(data).ConsumeUnicodeNoSurrogates(len(data))
    try:
        rel = _validate(url_path)
    except VaultPathError:
        return
    _check_validated(rel)
    for resolver in (resolve_md, resolve_asset):
        try:
            resolved = resolver(url_path, VAULT)
        except VaultPathError:
            continue
        if not resolved.is_relative_to(ROOT):
            raise AssertionError(f"{resolver.__name__}({url_path!r}) escaped to {resolved}")


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
