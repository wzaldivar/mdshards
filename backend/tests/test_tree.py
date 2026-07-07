from pathlib import Path

from app.tree import build_tree


def _names(node: dict) -> list[str]:
    """Flatten a tree to a sorted list of relative paths for assertion."""
    out: list[str] = []
    _flatten(node, out)
    return sorted(out)


def _flatten(node: dict, acc: list[str]) -> None:
    if node["type"] == "file":
        acc.append(node["path"])
    for child in node.get("children", []):
        _flatten(child, acc)


def test_build_tree_lists_files(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("a")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.md").write_text("b")
    assert _names(build_tree(tmp_path)) == ["a.md", "sub/b.md"]


def test_build_tree_skips_hidden(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("a")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "secret.md").write_text("nope")
    assert _names(build_tree(tmp_path)) == ["a.md"]


def test_build_tree_skips_symlink_escaping_root(tmp_path: Path) -> None:
    """A symlink inside the vault pointing OUTSIDE must not be traversed —
    the listing must never leak filenames from beyond the vault."""
    outside = tmp_path.parent / f"outside_{tmp_path.name}"
    outside.mkdir(exist_ok=True)
    (outside / "secret.md").write_text("nope")
    (tmp_path / "a.md").write_text("a")
    (tmp_path / "escape").symlink_to(outside)

    listed = _names(build_tree(tmp_path))
    assert "a.md" in listed
    assert not any("secret" in p for p in listed)
    assert not any("escape" in p for p in listed)


def test_build_tree_skips_broken_symlink(tmp_path: Path) -> None:
    """Broken symlinks can't be classified safely — skip them rather than
    surface entries the SPA can't navigate to."""
    (tmp_path / "a.md").write_text("a")
    (tmp_path / "broken").symlink_to(tmp_path / "does_not_exist")
    assert _names(build_tree(tmp_path)) == ["a.md"]


def test_build_tree_keeps_internal_symlink(tmp_path: Path) -> None:
    """A symlink whose resolved target stays inside the vault is allowed —
    the containment check is about escape, not about the symlink itself."""
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "note.md").write_text("hi")
    (tmp_path / "alias").symlink_to(tmp_path / "real")
    listed = _names(build_tree(tmp_path))
    assert "real/note.md" in listed
    # The alias also surfaces, since its target is inside-root.
    assert any(p.startswith("alias/") for p in listed)


def test_build_tree_missing_root(tmp_path: Path) -> None:
    missing = tmp_path / "no_such_vault"
    result = build_tree(missing)
    assert result == {"name": "", "path": "", "type": "dir", "children": []}
