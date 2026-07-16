"""Root-mount (no BASE_URL) journeys — deployment mode 1 as shipped."""

import re

from playwright.sync_api import Page, expect

from conftest import (
    ROOT_URL,
    ROOT_VAULT,
    TINY_PNG,
    click_editor,
    read_vault_file,
    seed_vault_file,
    type_text,
    wait_vault_file,
)


def _loaded_img_srcs(page: Page) -> list[str]:
    """Absolute srcs of every <img> that actually decoded (naturalWidth > 0)."""
    return page.eval_on_selector_all(
        "img",
        "els => els.filter(i => i.src && i.complete && i.naturalWidth > 0).map(i => i.src)",
    )


def test_home_loads_but_is_read_only(page: Page):
    """Demo: browse /, the CRDT editor mounts and the page loads (reads flow),
    but the landing page is read-only — the server drops writes to index, so
    typed text never lands in index.md. (The edit->persist loop is verified on a
    created note in test_quick_switcher_creates_note.)"""
    import time

    page.goto(f"{ROOT_URL}/")
    click_editor(page)
    expect(page.locator(".cm-content")).to_be_visible()
    marker = "e2e-home-should-not-persist"
    type_text(page, marker + " ")
    # A writable note persists within a beat; the index write is dropped, so
    # after a generous wait the marker must still be absent from disk.
    time.sleep(2)
    assert marker not in (read_vault_file(ROOT_VAULT, "index.md") or "")


def test_note_with_image_renders(page: Page):
    """An externally-written note embedding an externally-written image —
    the image must actually decode in the browser (naturalWidth > 0), not
    merely produce an <img> tag."""
    seed_vault_file(ROOT_VAULT, "gallery/pic.png", TINY_PNG)
    seed_vault_file(ROOT_VAULT, "gallery/note.md", b"# gallery\n\n![p](pic.png)\n")
    page.goto(f"{ROOT_URL}/gallery/note")
    expect(page.locator(".cm-content")).to_be_visible()
    page.wait_for_function(
        "() => [...document.querySelectorAll('img')]"
        ".some(i => i.src && i.complete && i.naturalWidth > 0)"
    )
    loaded = _loaded_img_srcs(page)
    assert any(src.endswith("/gallery/pic.png") for src in loaded), loaded


def test_quick_switcher_creates_note(page: Page, browser_name: str):
    """Cmd/Ctrl-K, type a fresh path, Shift-Enter: the ONLY UI surface that
    creates files implicitly — must create parents and navigate there."""
    # Engine-unique target: the vault is shared across the multi-engine matrix,
    # and create refuses an existing path — so a fixed name would 409 on the
    # second engine.
    target = f"created/by-e2e-{browser_name}"
    page.goto(f"{ROOT_URL}/")
    click_editor(page)
    page.keyboard.press("Control+k")
    switcher = page.get_by_placeholder(re.compile("go to or create", re.I))
    switcher.fill(target)
    switcher.press("Shift+Enter")
    expect(page).to_have_url(re.compile(rf"/{re.escape(target)}$"))
    click_editor(page)
    marker = "created-note-content"
    type_text(page, marker)
    wait_vault_file(ROOT_VAULT, f"{target}.md", marker)


def test_missing_path_renders_notfound_view(page: Page):
    """A typo'd URL serves the SPA shell and the React NotFound view — the
    'missing paths serve the shell' rule, browser-observed."""
    page.goto(f"{ROOT_URL}/no/such/note")
    expect(page.get_by_text(re.compile("not found", re.I))).to_be_visible()


def test_formerly_reserved_names_are_vault_paths(page: Page):
    """App-surface namespace regression: names that used to collide with the
    app's own routes — `assets` (the classic trap: old bundle mount at
    /assets), `api` — are ordinary vault paths now. Every mdshards surface
    moved under /_mdshards, so the whole top-level namespace is the vault's."""
    seed_vault_file(ROOT_VAULT, "assets/pic.png", TINY_PNG)
    seed_vault_file(ROOT_VAULT, "assets/note.md", b"# in an assets folder\n\n![p](pic.png)\n")
    seed_vault_file(ROOT_VAULT, "api.md", b"# a note literally named api\n")
    # A note in the once-reserved assets/ folder, embedding an image also under
    # assets/ — both resolve to the VAULT, not the frontend bundle mount.
    page.goto(f"{ROOT_URL}/assets/note")
    expect(page.locator(".cm-content")).to_be_visible()
    page.wait_for_function(
        "() => [...document.querySelectorAll('img')]"
        ".some(i => i.src && i.complete && i.naturalWidth > 0)"
    )
    loaded = _loaded_img_srcs(page)
    assert any(src.endswith("/assets/pic.png") for src in loaded), loaded
    # A top-level note literally named `api` opens in the editor, not the API.
    page.goto(f"{ROOT_URL}/api")
    expect(page.locator(".cm-content")).to_be_visible()
    expect(page.get_by_text("a note literally named api")).to_be_visible()
