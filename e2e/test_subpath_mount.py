"""Sub-path mount (BASE_URL=/wiki) journeys — the full-containment contract.

The browser talks straight to the container using prefixed URLs, which is
byte-for-byte what a prefix-preserving proxy (the documented single
PathPrefix rule) would forward.
"""

import re

from playwright.sync_api import Page, expect

from conftest import (
    CRDT_LOAD_TIMEOUT,
    TINY_PNG,
    WIKI_HOST,
    WIKI_PREFIX,
    WIKI_URL,
    WIKI_VAULT,
    click_editor,
    expect_editor_contains,
    quick_switch,
    seed_vault_file,
    type_text,
    wait_vault_file,
)


def _loaded_img_srcs(page: Page) -> list[str]:
    return page.eval_on_selector_all(
        "img",
        "els => els.filter(i => i.src && i.complete && i.naturalWidth > 0).map(i => i.src)",
    )


def test_shell_is_contained_under_prefix(page: Page):
    """The served shell carries the home-path meta and prefixed bundle refs,
    and NOTHING the page subsequently loads escapes the prefix."""
    page.goto(f"{WIKI_URL}/")
    expect(page.locator(".cm-content")).to_be_visible()
    expect(page.locator('meta[name="mdshards-home-path"]')).to_have_attribute(
        "content", WIKI_PREFIX
    )
    requests = page.evaluate(
        "() => performance.getEntriesByType('resource').map(e => e.name)"
    )
    origin_rooted = [
        u
        for u in requests
        if f"//{WIKI_HOST}" in u and f"//{WIKI_HOST}{WIKI_PREFIX}" not in u
    ]
    assert not origin_rooted, f"requests escaped the prefix: {origin_rooted}"


def test_lazy_chunks_load_under_prefix(page: Page, browser_name: str):
    """Code-split chunks (mermaid, code-block languages) are fetched after the
    shell, so the serve-time shell rewrite never sees them — Vite must emit
    them relative to the importing chunk or they escape the prefix."""
    note = f"lazy/diagram-{browser_name}"
    seed_vault_file(
        WIKI_VAULT,
        f"{note}.md",
        b"# lazy\n\n```mermaid\nflowchart LR\n  a --> b\n```\n\n"
        b"```python\nprint('hi')\n```\n\nend-of-note\n",
    )
    page.goto(f"{WIKI_URL}/{note}")
    expect_editor_contains(page, "end-of-note")
    expect(page.locator(".cm-md-mermaid svg")).to_be_visible(timeout=CRDT_LOAD_TIMEOUT)
    requests = page.evaluate(
        "() => performance.getEntriesByType('resource').map(e => e.name)"
    )
    origin_rooted = [
        u
        for u in requests
        if f"//{WIKI_HOST}" in u and f"//{WIKI_HOST}{WIKI_PREFIX}" not in u
    ]
    assert not origin_rooted, f"requests escaped the prefix: {origin_rooted}"


def test_edits_persist_under_prefix(page: Page):
    page.goto(f"{WIKI_URL}/")
    click_editor(page)
    marker = "e2e-wiki-roundtrip"
    type_text(page, marker + " ")
    wait_vault_file(WIKI_VAULT, "index.md", marker)


def test_note_with_image_renders_under_prefix(page: Page):
    """The 1.2.0 regression guard: in-note images must load at a sub-path
    mount with no extra proxy rules."""
    seed_vault_file(WIKI_VAULT, "gallery/pic.png", TINY_PNG)
    seed_vault_file(WIKI_VAULT, "gallery/note.md", b"# gallery\n\n![p](pic.png)\n")
    page.goto(f"{WIKI_URL}/gallery/note")
    expect(page.locator(".cm-content")).to_be_visible()
    page.wait_for_function(
        "() => [...document.querySelectorAll('img')]"
        ".some(i => i.src && i.complete && i.naturalWidth > 0)"
    )
    loaded = _loaded_img_srcs(page)
    assert any(f"{WIKI_PREFIX}/gallery/pic.png" in src for src in loaded), loaded


def test_vault_path_starting_with_prefix_segment(page: Page, browser_name: str):
    """A vault path whose first segment equals the mount segment: creating
    `wiki/foo` under BASE_URL=/wiki must be browsable at /wiki/wiki/foo —
    the prefix is applied once client-side and stripped once server-side."""
    # Engine-unique target (shared vault + 409-on-existing create).
    rel = f"wiki/foo-{browser_name}"
    page.goto(f"{WIKI_URL}/")
    click_editor(page)
    quick_switch(page, rel, create=True)
    expect(page).to_have_url(re.compile(rf"{re.escape(WIKI_PREFIX)}/{re.escape(rel)}$"))
    click_editor(page)
    marker = "shadow-segment-note"
    type_text(page, marker)
    wait_vault_file(WIKI_VAULT, f"{rel}.md", marker)

    # …and it survives a cold reload at the double-segment URL.
    page.goto(f"{WIKI_URL}/{rel}")
    expect_editor_contains(page, marker)
