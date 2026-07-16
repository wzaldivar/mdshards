from pathlib import Path

import pytest

from app.vault import VaultPathError, assert_inside, resolve_asset, resolve_md


def test_root_resolves_to_index(tmp_path: Path) -> None:
    assert resolve_md("", tmp_path) == (tmp_path / "index.md").resolve()


def test_root_slash_resolves_to_index(tmp_path: Path) -> None:
    assert resolve_md("/", tmp_path) == (tmp_path / "index.md").resolve()


def test_simple_md(tmp_path: Path) -> None:
    assert resolve_md("foo/bar", tmp_path) == (tmp_path / "foo" / "bar.md").resolve()


def test_leading_slash_stripped(tmp_path: Path) -> None:
    assert resolve_md("/foo/bar", tmp_path) == resolve_md("foo/bar", tmp_path)


def test_rejects_traversal_leading(tmp_path: Path) -> None:
    with pytest.raises(VaultPathError):
        resolve_md("../etc/passwd", tmp_path)


def test_rejects_traversal_mid(tmp_path: Path) -> None:
    with pytest.raises(VaultPathError):
        resolve_md("foo/../../etc/passwd", tmp_path)


def test_dot_segment_normalized(tmp_path: Path) -> None:
    assert resolve_md("./foo", tmp_path) == resolve_md("foo", tmp_path)


def test_allows_spaces(tmp_path: Path) -> None:
    assert resolve_md("foo bar", tmp_path) == (tmp_path / "foo bar.md").resolve()
    assert resolve_md("a dir/my note", tmp_path) == (tmp_path / "a dir" / "my note.md").resolve()


def test_rejects_null_byte(tmp_path: Path) -> None:
    with pytest.raises(VaultPathError):
        resolve_md("foo\x00bar", tmp_path)


def test_case_sensitive(tmp_path: Path) -> None:
    assert resolve_md("Foo", tmp_path) != resolve_md("foo", tmp_path)


def test_reserved_segment_rejected(tmp_path: Path) -> None:
    # `_mdshards` is the app-surface namespace; a vault path whose first
    # segment is it would collide, so it's rejected loudly (not a silent 404).
    with pytest.raises(VaultPathError):
        resolve_md("_mdshards", tmp_path)
    with pytest.raises(VaultPathError):
        resolve_md("_mdshards/api", tmp_path)
    with pytest.raises(VaultPathError):
        resolve_asset("_mdshards/pic.png", tmp_path)


def test_reserved_segment_only_top_level(tmp_path: Path) -> None:
    # Only the FIRST segment is reserved — a nested `_mdshards` never collides.
    assert (
        resolve_md("notes/_mdshards", tmp_path) == (tmp_path / "notes" / "_mdshards.md").resolve()
    )


def test_formerly_reserved_names_now_free(tmp_path: Path) -> None:
    # The whole point of the app-surface namespace: `assets`, `api`, `ws` are
    # ordinary vault names now — no silent shadowing by the bundle/API mounts.
    assert resolve_md("assets", tmp_path) == (tmp_path / "assets.md").resolve()
    assert resolve_md("api/notes", tmp_path) == (tmp_path / "api" / "notes.md").resolve()
    assert (
        resolve_asset("assets/diagram.png", tmp_path)
        == (tmp_path / "assets" / "diagram.png").resolve()
    )


def test_asset_keeps_extension(tmp_path: Path) -> None:
    assert (
        resolve_asset("foo/diagram.png", tmp_path) == (tmp_path / "foo" / "diagram.png").resolve()
    )


def test_asset_requires_extension(tmp_path: Path) -> None:
    with pytest.raises(VaultPathError):
        resolve_asset("foo/bar", tmp_path)


def test_asset_allows_spaces(tmp_path: Path) -> None:
    assert (
        resolve_asset("foo/has space.png", tmp_path)
        == (tmp_path / "foo" / "has space.png").resolve()
    )


def test_symlink_escape_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"outside_{tmp_path.name}"
    outside.mkdir(exist_ok=True)
    (outside / "secret.md").write_text("nope")
    (tmp_path / "link").symlink_to(outside)
    with pytest.raises(VaultPathError):
        resolve_md("link/secret", tmp_path)


# --- assert_inside ------------------------------------------------------------


def test_assert_inside_accepts_existing_path(tmp_path: Path) -> None:
    target = tmp_path / "foo.md"
    target.write_text("x")
    assert assert_inside(target, tmp_path) == target.resolve()


def test_assert_inside_accepts_nonexistent_path(tmp_path: Path) -> None:
    """`assert_inside` must work on paths whose final component doesn't exist
    yet — that's the case for any pre-write check (write_md_atomic of a brand
    new file, move dst, etc.)."""
    target = tmp_path / "a" / "b" / "new.md"
    assert assert_inside(target, tmp_path).is_relative_to(tmp_path.resolve())


def test_assert_inside_rejects_path_outside_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"outside_{tmp_path.name}"
    outside.mkdir(exist_ok=True)
    with pytest.raises(VaultPathError):
        assert_inside(outside / "evil.md", tmp_path)


def test_assert_inside_rejects_symlink_at_nonexistent_ancestor(tmp_path: Path) -> None:
    """The narrow defense-in-depth case: the immediate parent of the target
    doesn't exist yet, but an *ancestor further up* is a symlink pointing
    outside the root. `_resolve_nonexistent` walks up to the nearest existing
    dir and resolves it, so the escape is visible."""
    outside = tmp_path.parent / f"outside_{tmp_path.name}"
    outside.mkdir(exist_ok=True)
    (tmp_path / "trap").symlink_to(outside)
    # `tmp_path/trap/new/sub/file.md` — only `trap` exists; `new`, `sub` don't.
    target = tmp_path / "trap" / "new" / "sub" / "file.md"
    with pytest.raises(VaultPathError):
        assert_inside(target, tmp_path)


def test_assert_inside_rejects_absolute_path_outside(tmp_path: Path) -> None:
    outside = Path("/etc/passwd")
    with pytest.raises(VaultPathError):
        assert_inside(outside, tmp_path)
