from pathlib import Path

import pytest

from app import files
from app.files import (
    DEFAULT_INDEX_TEMPLATE,
    delete_with_prune,
    ensure_index_exists,
    move_with_prune,
    read_md,
    resolve_index_template,
    write_bytes_atomic,
    write_md_atomic,
)
from app.vault import VaultPathError


def test_write_atomic_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "c.md"
    write_md_atomic(target, "hello", tmp_path)
    assert target.read_text() == "hello"


def test_write_atomic_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "x.md"
    write_md_atomic(target, "v1", tmp_path)
    write_md_atomic(target, "v2", tmp_path)
    assert target.read_text() == "v2"


def test_write_atomic_no_tmp_residue(tmp_path: Path) -> None:
    target = tmp_path / "x.md"
    write_md_atomic(target, "hi", tmp_path)
    leftovers = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_delete_with_prune_claude_md_example(tmp_path: Path) -> None:
    """The CLAUDE.md example: deleting has_data/has_data/empty/empty/foo_only/foo.md
    leaves has_data/has_data/ intact and removes everything below."""
    deep = tmp_path / "has_data" / "has_data" / "empty" / "empty" / "foo_only" / "foo.md"
    sibling = tmp_path / "has_data" / "has_data" / "neighbor.md"
    write_md_atomic(deep, "x", tmp_path)
    write_md_atomic(sibling, "y", tmp_path)

    delete_with_prune(deep, tmp_path)

    assert sibling.exists()
    assert (tmp_path / "has_data" / "has_data").is_dir()
    assert not (tmp_path / "has_data" / "has_data" / "empty").exists()


def test_delete_with_prune_stops_at_vault_root(tmp_path: Path) -> None:
    only = tmp_path / "only.md"
    write_md_atomic(only, "x", tmp_path)
    delete_with_prune(only, tmp_path)
    assert tmp_path.exists()
    assert not only.exists()


def test_delete_with_prune_leaves_non_empty_dirs(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b.md"
    keep = tmp_path / "a" / "c.md"
    write_md_atomic(target, "x", tmp_path)
    write_md_atomic(keep, "y", tmp_path)
    delete_with_prune(target, tmp_path)
    assert (tmp_path / "a").is_dir()
    assert keep.exists()


def test_move_with_prune_creates_dest_dirs_and_drops_source_empties(tmp_path: Path) -> None:
    src = tmp_path / "old" / "nested" / "note.md"
    dst = tmp_path / "new" / "place" / "note.md"
    write_md_atomic(src, "content", tmp_path)

    move_with_prune(src, dst, tmp_path)

    assert dst.read_text() == "content"
    assert not src.exists()
    # Both source nesting dirs were left empty by the move and must be pruned.
    assert not (tmp_path / "old" / "nested").exists()
    assert not (tmp_path / "old").exists()
    # Destination nesting was created on demand.
    assert (tmp_path / "new" / "place").is_dir()


def test_move_with_prune_keeps_source_dir_when_other_files_remain(tmp_path: Path) -> None:
    src = tmp_path / "notes" / "a.md"
    sibling = tmp_path / "notes" / "b.md"
    write_md_atomic(src, "a", tmp_path)
    write_md_atomic(sibling, "b", tmp_path)

    move_with_prune(src, tmp_path / "moved" / "a.md", tmp_path)

    assert (tmp_path / "notes").is_dir()
    assert sibling.exists()


# --- containment guardrails ---------------------------------------------------
# These verify the primitives self-defend: even if a caller hands them a path
# that escapes the vault root, no disk action runs.


def _outside_dir(tmp_path: Path) -> Path:
    """A sibling directory of `tmp_path` that pytest will clean up too — used to
    stage paths that live OUTSIDE the vault root we pass into the primitives."""
    sibling = tmp_path.parent / f"outside_{tmp_path.name}"
    sibling.mkdir(exist_ok=True)
    return sibling


def test_write_md_atomic_rejects_path_outside_vault(tmp_path: Path) -> None:
    outside = _outside_dir(tmp_path) / "evil.md"
    with pytest.raises(VaultPathError):
        write_md_atomic(outside, "nope", tmp_path)
    assert not outside.exists()


def test_write_bytes_atomic_rejects_path_outside_vault(tmp_path: Path) -> None:
    outside = _outside_dir(tmp_path) / "evil.bin"
    with pytest.raises(VaultPathError):
        write_bytes_atomic(outside, b"nope", tmp_path)
    assert not outside.exists()


def test_read_md_rejects_path_outside_vault(tmp_path: Path) -> None:
    outside_file = _outside_dir(tmp_path) / "secret.md"
    outside_file.write_text("secret")
    with pytest.raises(VaultPathError):
        read_md(outside_file, tmp_path)


def test_write_md_atomic_rejects_traversal_via_symlinked_parent(tmp_path: Path) -> None:
    """A symlink planted at a not-yet-created parent dir must still be caught —
    `assert_inside` walks up to the nearest existing ancestor, resolves THAT,
    then re-attaches the missing tail, so the escape is visible before any
    mkdir/write happens."""
    outside = _outside_dir(tmp_path)
    (tmp_path / "trap").symlink_to(outside)
    target = tmp_path / "trap" / "nested" / "evil.md"
    with pytest.raises(VaultPathError):
        write_md_atomic(target, "nope", tmp_path)
    assert not (outside / "nested" / "evil.md").exists()


def test_move_with_prune_rejects_dst_outside_vault(tmp_path: Path) -> None:
    src = tmp_path / "good.md"
    write_md_atomic(src, "x", tmp_path)
    dst = _outside_dir(tmp_path) / "bad.md"
    with pytest.raises(VaultPathError):
        move_with_prune(src, dst, tmp_path)
    assert src.exists()
    assert not dst.exists()


def test_move_with_prune_rejects_dst_via_symlinked_parent(tmp_path: Path) -> None:
    """The narrow gap the audit flagged: when `dst.parent` doesn't exist yet,
    the old code skipped `resolve()` on it. A symlink planted at a
    not-yet-created ancestor would have evaded the containment check. Now it
    doesn't."""
    src = tmp_path / "good.md"
    write_md_atomic(src, "x", tmp_path)
    outside = _outside_dir(tmp_path)
    (tmp_path / "trap").symlink_to(outside)
    dst = tmp_path / "trap" / "new" / "bad.md"
    with pytest.raises(VaultPathError):
        move_with_prune(src, dst, tmp_path)
    assert src.exists()
    assert not (outside / "new" / "bad.md").exists()


def test_delete_with_prune_rejects_path_outside_vault(tmp_path: Path) -> None:
    outside_file = _outside_dir(tmp_path) / "keep.md"
    outside_file.write_text("keep")
    with pytest.raises(VaultPathError):
        delete_with_prune(outside_file, tmp_path)
    assert outside_file.exists()


def test_ensure_index_materializes_from_builtin_default(tmp_path: Path, monkeypatch) -> None:
    # No override mounted → built-in default seeds index.md.
    monkeypatch.setattr(files, "OVERRIDE_INDEX_TEMPLATE", tmp_path / "absent.md")
    created = ensure_index_exists(tmp_path)
    assert created is True
    assert (tmp_path / "index.md").read_text() == DEFAULT_INDEX_TEMPLATE.read_text()


def test_ensure_index_noop_when_present(tmp_path: Path) -> None:
    (tmp_path / "index.md").write_text("existing")
    created = ensure_index_exists(tmp_path)
    assert created is False
    assert (tmp_path / "index.md").read_text() == "existing"


def test_ensure_index_uses_mounted_override(tmp_path: Path, monkeypatch) -> None:
    override = tmp_path / "override.md"
    override.write_text("# Custom seed\n")
    monkeypatch.setattr(files, "OVERRIDE_INDEX_TEMPLATE", override)
    vault = tmp_path / "vault"
    created = ensure_index_exists(vault)
    assert created is True
    assert (vault / "index.md").read_text() == "# Custom seed\n"


def test_resolve_index_template_prefers_mounted_override(tmp_path: Path, monkeypatch) -> None:
    override = tmp_path / "override.md"
    override.write_text("x")
    monkeypatch.setattr(files, "OVERRIDE_INDEX_TEMPLATE", override)
    assert resolve_index_template() == override
    # Absent override → built-in default.
    monkeypatch.setattr(files, "OVERRIDE_INDEX_TEMPLATE", tmp_path / "gone.md")
    assert resolve_index_template() == DEFAULT_INDEX_TEMPLATE
