"""Root-mount (no BASE_URL) journeys — deployment mode 1 as shipped."""

import re

from playwright.sync_api import Page, expect

from conftest import (
    ROOT_URL,
    CRDT_LOAD_TIMEOUT,
    ROOT_VAULT,
    TINY_PNG,
    click_editor,
    expect_editor_contains,
    expect_note_text,
    read_vault_file,
    quick_switch,
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
    expect(page.locator(".cm-content")).to_be_visible()
    # The demo landing page shows off a mermaid diagram; it must actually
    # render (bundled, lazy-loaded) rather than sit as a raw fence.
    expect(page.locator(".cm-md-mermaid svg")).to_be_visible(timeout=CRDT_LOAD_TIMEOUT)
    click_editor(page)
    marker = "e2e-home-should-not-persist"
    type_text(page, marker + " ")
    # A writable note persists within a beat; the index write is dropped, so
    # after a generous wait the marker must still be absent from disk.
    time.sleep(2)
    assert marker not in (read_vault_file(ROOT_VAULT, "index.md") or "")


def test_uploads_are_disabled(page: Page, browser_name: str):
    """Demo: Cmd/Ctrl-U still opens the OS file picker, but picking a file only
    shows a notice — nothing is sent. The asset upload endpoint is gone
    server-side too, so a hand-rolled request can't bypass the UI."""
    note = f"demo/upload-{browser_name}"
    seed_vault_file(ROOT_VAULT, f"{note}.md", b"upload-body\n")
    page.goto(f"{ROOT_URL}/{note}")
    expect_editor_contains(page, "upload-body")

    sent: list[str] = []
    page.on(
        "request",
        lambda r: sent.append(r.url) if r.method != "GET" and "/_mdshards/api/" in r.url else None,
    )
    with page.expect_file_chooser() as fc:
        page.keyboard.press("Control+u")
    fc.value.set_files(
        files=[{"name": f"up-{browser_name}.png", "mimeType": "image/png", "buffer": TINY_PNG}]
    )
    expect(page.get_by_text("Uploads are disabled in this demo.")).to_be_visible()
    assert not sent, f"upload UI sent requests: {sent}"
    assert read_vault_file(ROOT_VAULT, f"up-{browser_name}.png") is None

    status = page.evaluate(
        """async (name) => {
            const body = new FormData()
            body.append('path', name)
            body.append('file', new Blob([new Uint8Array([137, 80, 78, 71])]), name)
            const r = await fetch('/_mdshards/api/assets', { method: 'POST', body })
            return r.status
        }""",
        f"direct-{browser_name}.png",
    )
    assert status in (404, 405), status
    assert read_vault_file(ROOT_VAULT, f"direct-{browser_name}.png") is None


def test_external_image_renders_a_picsum_placeholder(page: Page, browser_name: str):
    """Demo: an image ref that isn't a vault path renders a Lorem Picsum
    placeholder instead — the external host is never contacted. Picsum is
    stubbed (the test network is offline) to prove the <img> really loads it."""
    external = "https://images.example.com/cat.png"
    hits: list[str] = []
    page.route(
        "https://images.example.com/**", lambda r: (hits.append(r.request.url), r.abort())
    )
    page.route(
        "https://picsum.photos/**",
        lambda r: r.fulfill(status=200, content_type="image/png", body=TINY_PNG),
    )
    note = f"demo/external-img-{browser_name}"
    seed_vault_file(ROOT_VAULT, f"{note}.md", f"# ext\n\n![cat]({external})\n".encode())
    page.goto(f"{ROOT_URL}/{note}")
    expect(page.locator(".cm-content")).to_be_visible()
    page.wait_for_function(
        "() => [...document.querySelectorAll('img')].some(i =>"
        " i.src.startsWith('https://picsum.photos/') && i.complete && i.naturalWidth > 0)",
        timeout=CRDT_LOAD_TIMEOUT,
    )
    srcs = page.eval_on_selector_all("img", "els => els.map(i => i.src)")
    assert external not in srcs, srcs
    assert not hits, f"external image host was contacted: {hits}"


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
    quick_switch(page, target, create=True)
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
    expect_note_text(page, "a note literally named api")
