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


def _fail(called: str, got: str, expected: str) -> None:
    """Report a broken invariant as call / got / expected. The three labelled
    lines are what `.github/scripts/pr_report.py` lifts into the PR comment,
    so a crash reads like a failed assertion instead of a wall of bytes."""
    raise AssertionError(
        f"fuzz invariant violated\ncalled:   {called}\ngot:      {got}\nexpected: {expected}"
    )


def _check_validated(url_path: str, rel: str) -> None:
    called = f"_validate({url_path!r})"
    got = f"returned {rel!r}"
    if rel == "":
        return
    if rel.startswith("/"):
        _fail(called, got, "VaultPathError, or a relative path (no leading '/')")
    if "\x00" in rel:
        _fail(called, got, "VaultPathError (null byte in path)")
    if "\\" in rel:
        _fail(called, got, "VaultPathError (backslash in path)")
    parts = rel.split("/")
    if parts[0] == "_mdshards":
        _fail(called, got, "VaultPathError ('_mdshards' is the reserved first segment)")
    for bad in ("", ".", ".."):
        if bad in parts:
            _fail(called, got, f"VaultPathError (illegal path segment {bad!r})")


def TestOneInput(data: bytes) -> None:
    url_path = atheris.FuzzedDataProvider(data).ConsumeUnicodeNoSurrogates(len(data))
    try:
        rel = _validate(url_path)
    except VaultPathError:
        return
    except Exception as exc:  # noqa: BLE001 — any other exception is the finding
        _fail(
            f"_validate({url_path!r})",
            f"raised {type(exc).__name__}: {exc}",
            "a validated path, or VaultPathError",
        )
    _check_validated(url_path, rel)
    for resolver in (resolve_md, resolve_asset):
        called = f"{resolver.__name__}({url_path!r}, <vault>)"
        try:
            resolved = resolver(url_path, VAULT)
        except VaultPathError:
            continue
        except Exception as exc:  # noqa: BLE001
            _fail(
                called,
                f"raised {type(exc).__name__}: {exc}",
                "a path inside the vault, or VaultPathError",
            )
        if not resolved.is_relative_to(ROOT):
            _fail(
                called,
                f"returned {str(resolved)!r}, outside the vault root {str(ROOT)!r}",
                "a path inside the vault, or VaultPathError",
            )


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
