"""Keyboard-first switcher journeys — real browser, real container.

These are the shortcuts that have regressed repeatedly (Cmd/Ctrl-K quick
switcher, Ctrl-Shift-K rename, Ctrl-Backspace delete, Ctrl-E emoji), so each
is driven end to end here: the chord fires, the modal opens, its core action
lands (navigation / disk write / deletion). The last test guards the fragile
case specifically — a shortcut fired while focus is inside the AssetViewer's
iframe (an asset URL), which relies on the per-iframe shortcut rebind.

Playwright locators auto-wait and re-resolve on every action, so the modal
input is looked up fresh each time — no stale-element retries needed. The
Linux-container browsers map the app's Cmd/Ctrl bindings to CONTROL.
"""

import re

from playwright.sync_api import Page, expect

from conftest import (
    ROOT_URL,
    ROOT_VAULT,
    click_editor,
    expect_editor_contains,
    poll_until,
    read_vault_file,
    seed_vault_file,
    wait_vault_file,
)

GO_TO = re.compile("go to or create", re.I)
PICK_FILE = re.compile("pick a file to delete", re.I)
RENAME_TO = re.compile("rename to", re.I)
INSERT_EMOJI = re.compile("insert emoji", re.I)


# ---- quick switcher (Ctrl-K) ----


def test_quick_switcher_navigates_to_existing_note(page: Page):
    seed_vault_file(ROOT_VAULT, "swq/target.md", b"swq-target-body\n")
    page.goto(f"{ROOT_URL}/")
    expect(page.locator(".cm-content")).to_be_visible()

    page.keyboard.press("Control+k")
    switcher = page.get_by_placeholder(GO_TO)
    switcher.fill("swq/target")
    # plain Enter navigates to an existing MATCH — wait for the async tree
    # fetch to surface the row (and thus select it) before pressing, or Enter
    # fires against an empty match list and no-ops.
    expect(page.get_by_role("button", name="swq/target")).to_be_visible()
    switcher.press("Enter")

    expect(page).to_have_url(re.compile(r"/swq/target$"))
    expect_editor_contains(page, "swq-target-body")


def test_quick_switcher_escape_closes_and_stays_put(page: Page):
    page.goto(f"{ROOT_URL}/")
    expect(page.locator(".cm-content")).to_be_visible()
    page.keyboard.press("Control+k")
    switcher = page.get_by_placeholder(GO_TO)
    expect(switcher).to_be_visible()
    switcher.press("Escape")
    expect(page.get_by_placeholder(GO_TO)).to_have_count(0)
    expect(page).to_have_url(re.compile(re.escape(ROOT_URL) + r"/?$"))


# ---- delete switcher (Ctrl-Backspace) ----


def test_delete_switcher_confirms_then_deletes_current_and_navigates_home(page: Page):
    seed_vault_file(ROOT_VAULT, "swd/victim.md", b"swd-victim-body\n")
    page.goto(f"{ROOT_URL}/swd/victim")
    expect_editor_contains(page, "swd-victim-body")

    page.keyboard.press("Control+Backspace")
    switcher = page.get_by_placeholder(PICK_FILE)
    # top entry "Delete this file (swd/victim)" is preselected; first Enter arms
    switcher.press("Enter")
    expect(page.get_by_text(re.compile("confirm delete", re.I))).to_be_visible()
    # second Enter commits the delete
    switcher.press("Enter")

    # deleting the file being viewed navigates home and removes it from disk
    expect(page).to_have_url(re.compile(re.escape(ROOT_URL) + r"/?$"))
    poll_until(lambda: read_vault_file(ROOT_VAULT, "swd/victim.md") is None)


def test_delete_other_file_leaves_current_view(page: Page, browser_name: str):
    # Deleting an UNRELATED file (not the one open) must remove only it and leave
    # the current view in place — the counterpart to the delete-current journey.
    keep, victim = f"swd2/keep-{browser_name}", f"swd2/other-{browser_name}"
    seed_vault_file(ROOT_VAULT, f"{keep}.md", b"swd2-keeper-body\n")
    seed_vault_file(ROOT_VAULT, f"{victim}.md", b"swd2-other-body\n")
    page.goto(f"{ROOT_URL}/{keep}")
    expect_editor_contains(page, "swd2-keeper-body")

    page.keyboard.press("Control+Backspace")
    switcher = page.get_by_placeholder(PICK_FILE)
    # Typing the victim's path moves the highlight to its row (best match), past
    # the preselected "delete this file" top entry.
    switcher.fill(victim)
    expect(page.get_by_role("button", name=victim)).to_be_visible()
    switcher.press("Enter")  # arm confirm on the victim
    expect(page.get_by_text(re.compile("confirm delete", re.I))).to_be_visible()
    switcher.press("Enter")  # commit

    # Stay put on `keep`; only the victim is gone.
    expect(page).to_have_url(re.compile(rf"/{re.escape(keep)}$"))
    poll_until(lambda: read_vault_file(ROOT_VAULT, f"{victim}.md") is None)
    assert read_vault_file(ROOT_VAULT, f"{keep}.md") is not None
    expect_editor_contains(page, "swd2-keeper-body")


# ---- rename switcher (Ctrl-Shift-K) ----


def test_rename_switcher_moves_note_and_navigates(page: Page, browser_name: str):
    # Engine-unique src/dst — the shared vault + a 409-on-existing move endpoint
    # would otherwise collide across the multi-engine matrix.
    src, dst = f"swr/old-{browser_name}", f"swr/new-{browser_name}"
    seed_vault_file(ROOT_VAULT, f"{src}.md", b"swr-rename-body\n")
    page.goto(f"{ROOT_URL}/{src}")
    expect_editor_contains(page, "swr-rename-body")

    page.keyboard.press("Control+Shift+K")
    # prefilled with the current doc-id; fill() clears it and types the new one
    page.get_by_placeholder(RENAME_TO).fill(dst)
    page.get_by_placeholder(RENAME_TO).press("Enter")

    expect(page).to_have_url(re.compile(rf"/{re.escape(dst)}$"))
    wait_vault_file(ROOT_VAULT, f"{dst}.md", "swr-rename-body")
    assert read_vault_file(ROOT_VAULT, f"{src}.md") is None


# ---- emoji picker (Ctrl-E) ----


def test_emoji_picker_inserts_shortcode(page: Page, browser_name: str):
    # Engine-unique path (see the glyph test): the note lingers in server memory
    # for the grace period, so a shared path lets one engine's run reconcile
    # against the next engine's re-seed and the insert fails to land on disk.
    note = f"swe/note-{browser_name}"
    seed_vault_file(ROOT_VAULT, f"{note}.md", b"emoji-seed \n")
    page.goto(f"{ROOT_URL}/{note}")
    expect(page.locator(".cm-content")).to_be_visible()
    click_editor(page)  # a live buffer + cursor for the insert

    page.keyboard.press("Control+e")
    page.get_by_placeholder(INSERT_EMOJI).fill("smile")
    # wait for the (lazily bundled) gemoji dataset to load and rank a match
    expect(page.get_by_text(":smile:").first).to_be_visible()
    page.get_by_placeholder(INSERT_EMOJI).press("Enter")

    # the FILE keeps the literal shortcode; the glyph is render-time only
    wait_vault_file(ROOT_VAULT, f"{note}.md", ":smile:")


def test_emoji_picker_shift_enter_inserts_literal_glyph(page: Page, browser_name: str):
    # Engine-unique path: this note lingers in server memory for the grace
    # period, so a shared path would let one engine's run reconcile against
    # the next engine's re-seed (same reason the rename test isolates paths).
    note = f"swg/note-{browser_name}"
    seed_vault_file(ROOT_VAULT, f"{note}.md", b"glyph-seed \n")
    page.goto(f"{ROOT_URL}/{note}")
    expect(page.locator(".cm-content")).to_be_visible()
    click_editor(page)  # a live buffer + cursor for the insert

    page.keyboard.press("Control+e")
    page.get_by_placeholder(INSERT_EMOJI).fill("t-rex")
    # wait for the (lazily bundled) gemoji dataset to load and rank the match
    expect(page.get_by_text(":t-rex:").first).to_be_visible()
    # Shift-Enter is the glyph variant: the literal 🦖 lands in the FILE (not
    # the `:t-rex:` shortcode) — the one-way rule, exercised on disk.
    page.get_by_placeholder(INSERT_EMOJI).press("Shift+Enter")

    raw = wait_vault_file(ROOT_VAULT, f"{note}.md", "🦖")
    assert ":t-rex:" not in raw


# ---- asset-URL context: the shortcut rebind inside the AssetViewer iframe ----


def test_shortcut_fires_from_inside_asset_iframe(page: Page):
    """A text asset renders in a same-origin iframe that re-binds the global
    shortcuts on its contentDocument. With focus inside that iframe, Ctrl-K
    must still open the quick switcher — the 'works on asset URLs too' rule
    that broke before. Reached via in-app nav (a direct HTTP hit to an asset
    URL yields the browser's native viewer, not the AssetViewer)."""
    seed_vault_file(ROOT_VAULT, "swa/readme.txt", b"asset-iframe-body\n")
    page.goto(f"{ROOT_URL}/")
    expect(page.locator(".cm-content")).to_be_visible()

    # in-app nav through the quick switcher mounts the AssetViewer
    page.keyboard.press("Control+k")
    page.get_by_placeholder(GO_TO).fill("swa/readme.txt")
    expect(page.get_by_role("button", name="swa/readme.txt")).to_be_visible()
    page.get_by_placeholder(GO_TO).press("Enter")

    # focus goes into the iframe's document — the window binding no longer
    # sees the keydown; only the rebind on contentDocument does
    page.frame_locator("iframe").locator("body").click()
    page.keyboard.press("Control+k")
    expect(page.get_by_placeholder(GO_TO)).to_be_visible()
