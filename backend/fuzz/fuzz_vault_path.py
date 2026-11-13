"""Fuzz the path-traversal boundary (`app/vault.py`).

The app reaches the vault through exactly two functions, `resolve_md` and
`resolve_asset` — every router and the CRDT layer call one of them with a URL
path. Those are what is fuzzed and what a failure is reported against; the
private `_validate` they share is covered through them, not called directly.

The contract, for any URL path: either `VaultPathError` is raised, or the
returned path is inside the vault root. And some URLs must ALWAYS raise,
whatever they would resolve to: one carrying a null byte, a backslash, a `..`
segment, or the reserved first segment `_mdshards`. Symlinks planted inside
the vault (pointing out of it, dangling or not) must never yield an outside
path.

Run locally (Linux, from backend/):  PYTHONPATH=. python fuzz/fuzz_vault_path.py
"""

import os
import sys
import tempfile
from pathlib import Path

import atheris

with atheris.instrument_imports():
    from app.vault import VaultPathError, resolve_asset, resolve_md


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


def _must_reject(url_path: str) -> str | None:
    """Why this URL may never resolve, or None if it is allowed to. Judged
    from the URL alone, independently of how vault.py parses it. Empty and
    `.` segments are not here: they are normalized away, not rejected."""
    if "\x00" in url_path:
        return "null byte in the path"
    if "\\" in url_path:
        return "backslash in the path"
    segments = [s for s in url_path.lstrip("/").split("/") if s not in ("", ".")]
    if ".." in segments:
        return "'..' path segment"
    if segments and segments[0] == "_mdshards":
        return "'_mdshards' is the reserved first segment"
    return None


def TestOneInput(data: bytes) -> None:
    url_path = atheris.FuzzedDataProvider(data).ConsumeUnicodeNoSurrogates(len(data))
    forbidden = _must_reject(url_path)
    for resolver in (resolve_md, resolve_asset):
        called = f"{resolver.__name__}({url_path!r}, <vault>)"
        try:
            resolved = resolver(url_path, VAULT)
        except VaultPathError:
            continue
        except Exception as exc:  # noqa: BLE001 — any other exception is the finding
            _fail(
                called,
                f"raised {type(exc).__name__}: {exc}",
                "a path inside the vault, or VaultPathError",
            )
        # Judge containment on the fully resolved path, not the returned one:
        # a returned path can still hold `..` behind a directory that doesn't
        # exist yet, which compares as "inside" lexically while pointing out.
        real = resolved.resolve()
        inside = real.is_relative_to(ROOT)
        # Shown relative to the throwaway vault: its temp dir is noise.
        shown = f"<vault>/{real.relative_to(ROOT).as_posix()}" if inside else str(real)
        if not inside:
            _fail(
                called,
                f"returned {shown!r}, outside the vault",
                "a path inside the vault, or VaultPathError",
            )
        if forbidden:
            _fail(called, f"returned {shown!r}", f"VaultPathError ({forbidden})")


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
