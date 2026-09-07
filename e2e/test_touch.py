"""Keyboardless touch-device journeys — real browser, mobile emulation.

The app is keyboard-first: every vault operation hangs off a Cmd/Ctrl chord
(see test_switchers.py). A phone can't produce one, so the TouchBar exposes the
same actions as tap targets and vim mode is clamped off. These journeys drive
that end to end with the keyboard genuinely unused — every interaction here is
a tap, except `fill()` on the switcher input, which stands in for the software
keyboard the emulated device doesn't have.

Engine coverage: Chromium + WebKit. Firefox's Playwright backend rejects
`is_mobile`, and mobile Firefox is not a target — the point of the matrix here
is WebKit, since iOS Safari is where a real user meets this UI.
"""

import re

import pytest
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
INSERT_EMOJI = re.compile("insert emoji", re.I)

# A phone-shaped context. `is_mobile` is what flips the CSS pointer/hover
# capabilities to `(pointer: coarse) and (hover: none)` — the exact query
# frontend/src/lib/touch.ts gates the TouchBar on — so this is emulating the
# capability the feature keys off, not merely a small viewport.
PHONE = {
    "viewport": {"width": 390, "height": 844},
    "device_scale_factor": 3,
    "is_mobile": True,
    "has_touch": True,
}


@pytest.fixture
def touch_page(browser, browser_name: str):  # noqa: ANN001
    if browser_name == "firefox":
        pytest.skip("Playwright's Firefox backend does not support is_mobile emulation")
    context = browser.new_context(**PHONE)
    page = context.new_page()
    yield page
    context.close()


def test_touch_bar_is_absent_on_a_desktop_pointer(page: Page):
    """The desktop chrome stays uncluttered — the bar is touch-only."""
    page.goto(f"{ROOT_URL}/")
    expect(page.locator(".cm-content")).to_be_visible()
    expect(page.get_by_label("Editor actions")).to_have_count(0)


def test_touch_bar_renders_the_keyboardless_actions(touch_page: Page):
    touch_page.goto(f"{ROOT_URL}/")
    expect(touch_page.locator(".cm-content")).to_be_visible()

    bar = touch_page.get_by_label("Editor actions")
    expect(bar).to_be_visible()
    # Every Cmd/Ctrl chord from FEATURES.md's keyboard map has a tap target.
    for label in (
        "Open or create a note",
        "Insert emoji",
        "Upload a file",
        "Rename this file",
        "Delete a file",
        "Editor options",
    ):
        expect(bar.get_by_label(label)).to_be_visible()


def test_touch_bar_opens_switcher_and_navigates_without_a_keyboard(
    touch_page: Page, browser_name: str
):
    """The core journey: reach another note using taps only."""
    target = f"touch-{browser_name}/target"
    seed_vault_file(ROOT_VAULT, f"{target}.md", b"touch-nav-body\n")

    touch_page.goto(f"{ROOT_URL}/")
    expect(touch_page.locator(".cm-content")).to_be_visible()

    # Tap, don't press Ctrl-K — that chord does not exist on this device.
    touch_page.get_by_label("Open or create a note").tap()
    switcher = touch_page.get_by_placeholder(GO_TO)
    expect(switcher).to_be_visible()
    switcher.fill(target)

    # And commit by tapping the row rather than pressing Enter.
    row = touch_page.get_by_role("button", name=target)
    expect(row).to_be_visible()
    row.tap()

    expect(touch_page).to_have_url(re.compile(re.escape(target) + r"$"))
    expect_editor_contains(touch_page, "touch-nav-body")


def test_options_panel_drops_desktop_only_rows_and_offers_a_tappable_close(touch_page: Page):
    touch_page.goto(f"{ROOT_URL}/")
    expect(touch_page.locator(".cm-content")).to_be_visible()

    # `.first` — the TouchBar button and the dialog it opens share the label.
    touch_page.get_by_label("Editor options").first.tap()
    # Assertions are scoped to the dialog on purpose: the default index note's
    # own body lists the shortcuts ("...editor options (vim mode, ...)"), so a
    # page-wide text locator matches the NOTE, not the panel.
    panel = touch_page.locator("dialog")
    expect(panel).to_be_visible()

    # Vim needs Escape / `:` / hjkl — hidden rather than offered-then-ignored.
    expect(panel.get_by_text("Vim mode")).to_have_count(0)
    # Typewriter scrolling centres into the region the software keyboard
    # covers, so it's hidden on touch too.
    expect(panel.get_by_text("Center current line")).to_have_count(0)
    # The pointer-agnostic prefs stay available.
    expect(panel.get_by_text("Show line numbers")).to_be_visible()
    # The Alt-accelerator chips go too — there's no Alt key to press.
    expect(panel.get_by_text("⌥N")).to_have_count(0)

    # There's no Escape key, so the panel must be dismissable by tap.
    panel.get_by_role("button", name="Close", exact=True).tap()
    expect(touch_page.locator("dialog")).to_have_count(0)


def test_desktop_only_prefs_stay_off_on_touch_even_when_stored_on(touch_page: Page):
    """A profile that enabled vim / centring on a desktop must not have them
    applied on a phone — vim would swallow every keystroke, and centring would
    aim the cursor line at the region the software keyboard covers."""
    touch_page.add_init_script(
        "localStorage.setItem('mdshards:vim', '1');"
        "localStorage.setItem('mdshards:centerLine', '1')"
    )
    touch_page.goto(f"{ROOT_URL}/")
    expect(touch_page.locator(".cm-content")).to_be_visible()

    # The mode badge only renders while the vim keymap is live.
    expect(touch_page.get_by_text("NORMAL", exact=True)).to_have_count(0)
    # The clamps are on read, not a storage write — the desktop choices survive.
    assert touch_page.evaluate("localStorage.getItem('mdshards:vim')") == "1"
    assert touch_page.evaluate("localStorage.getItem('mdshards:centerLine')") == "1"


# ---- gestures that need a modifier key the software keyboard cannot produce ----


def test_create_a_note_by_tapping_the_create_row(touch_page: Page, browser_name: str):
    """Shift-Enter is the keyboard create gesture, and a phone cannot press it.

    The quick switcher is the app's ONLY file-creating surface, so without a
    tappable create row a touch user cannot create a note at all.
    """
    target = f"touch-create-{browser_name}/fresh"
    assert read_vault_file(ROOT_VAULT, f"{target}.md") is None, "path must start absent"

    touch_page.goto(f"{ROOT_URL}/")
    expect(touch_page.locator(".cm-content")).to_be_visible()

    touch_page.get_by_label("Open or create a note").tap()
    touch_page.get_by_placeholder(GO_TO).fill(target)

    create_row = touch_page.get_by_role("button", name=re.compile(r"^Create ", re.I))
    expect(create_row).to_be_visible()
    # No Shift-Enter chip on touch — there is no Shift key to advertise.
    expect(create_row).not_to_contain_text("Shift-Enter")
    create_row.tap()

    # The note is created on disk AND navigated to, all without a keyboard.
    expect(touch_page).to_have_url(re.compile(re.escape(target) + r"$"))
    wait_vault_file(ROOT_VAULT, f"{target}.md", "")


def test_emoji_glyph_mode_replaces_shift_enter(touch_page: Page, browser_name: str):
    """Shift-Enter writes the literal glyph; on touch that modifier becomes a
    visible mode toggle, so both insert forms stay reachable by tapping."""
    note = f"touch-glyph-{browser_name}/note"
    seed_vault_file(ROOT_VAULT, f"{note}.md", b"touch-glyph-seed \n")
    touch_page.goto(f"{ROOT_URL}/{note}")
    expect(touch_page.locator(".cm-content")).to_be_visible()
    click_editor(touch_page)  # a live buffer + cursor for the insert

    touch_page.get_by_label("Insert emoji").tap()
    touch_page.get_by_placeholder(INSERT_EMOJI).fill("t-rex")
    expect(touch_page.get_by_text(":t-rex:").first).to_be_visible()

    # Arm the glyph mode — the stand-in for holding Shift.
    touch_page.get_by_role("button", name="glyph", exact=True).tap()
    touch_page.get_by_text(":t-rex:").first.tap()

    raw = wait_vault_file(ROOT_VAULT, f"{note}.md", "\U0001f996")
    assert ":t-rex:" not in raw


def test_emoji_defaults_to_shortcode_mode(touch_page: Page, browser_name: str):
    """The toggle defaults to `:code:`, matching what a plain Enter/tap has
    always written — arming glyph mode must be a deliberate act."""
    note = f"touch-code-{browser_name}/note"
    seed_vault_file(ROOT_VAULT, f"{note}.md", b"touch-code-seed \n")
    touch_page.goto(f"{ROOT_URL}/{note}")
    expect(touch_page.locator(".cm-content")).to_be_visible()
    click_editor(touch_page)

    touch_page.get_by_label("Insert emoji").tap()
    touch_page.get_by_placeholder(INSERT_EMOJI).fill("smile")
    expect(touch_page.get_by_text(":smile:").first).to_be_visible()
    touch_page.get_by_text(":smile:").first.tap()

    wait_vault_file(ROOT_VAULT, f"{note}.md", ":smile:")


# ---- the Back button is the phone's dismiss gesture ----


def test_back_button_closes_a_dialog_instead_of_navigating_away(touch_page: Page, browser_name: str):
    """A modal is React state, not a route. Without a history sentinel Back
    would sail past it and leave the note entirely."""
    note = f"touch-back-{browser_name}/note"
    seed_vault_file(ROOT_VAULT, f"{note}.md", b"touch-back-body\n")
    touch_page.goto(f"{ROOT_URL}/{note}")
    expect(touch_page.locator(".cm-content")).to_be_visible()

    touch_page.get_by_label("Open or create a note").tap()
    expect(touch_page.get_by_placeholder(GO_TO)).to_be_visible()

    touch_page.go_back()

    # Dialog dismissed, and we are still on the same note.
    expect(touch_page.get_by_placeholder(GO_TO)).to_have_count(0)
    expect(touch_page).to_have_url(re.compile(re.escape(note) + r"$"))
    expect_editor_contains(touch_page, "touch-back-body")


def test_back_after_dismissing_a_dialog_still_leaves_the_note(touch_page: Page, browser_name: str):
    """Closing by tapping the scrim must remove the sentinel too — otherwise
    the next Back is swallowed by a leftover entry and appears to do nothing."""
    note = f"touch-back2-{browser_name}/note"
    seed_vault_file(ROOT_VAULT, f"{note}.md", b"touch-back2-body\n")
    touch_page.goto(f"{ROOT_URL}/")
    expect(touch_page.locator(".cm-content")).to_be_visible()
    touch_page.goto(f"{ROOT_URL}/{note}")
    expect_editor_contains(touch_page, "touch-back2-body")

    # Open a dialog and dismiss it WITHOUT Back. The options panel's Close is a
    # real button; the switchers' scrim is centred behind the modal, so tapping
    # it is not a reliable actionability target in a test.
    touch_page.get_by_label("Editor options").first.tap()
    panel = touch_page.locator("dialog")
    expect(panel).to_be_visible()
    panel.get_by_role("button", name="Close", exact=True).tap()
    expect(touch_page.locator("dialog")).to_have_count(0)

    # The sentinel is removed via history.back(), which is async — wait for it
    # to land before pressing Back, or the two races.
    touch_page.wait_for_function("() => !window.history.state?.mdshardsModal")

    # ONE Back press must leave the note — not two.
    touch_page.go_back()
    expect(touch_page).not_to_have_url(re.compile(re.escape(note) + r"$"))


def test_navigating_from_a_dialog_does_not_cost_a_dead_back_press(
    touch_page: Page, browser_name: str
):
    """The commit-by-navigating case: the sentinel is replaced, not buried, so
    Back returns to the origin note in a single press."""
    origin = f"touch-back3-{browser_name}/origin"
    target = f"touch-back3-{browser_name}/target"
    seed_vault_file(ROOT_VAULT, f"{origin}.md", b"touch-back3-origin\n")
    seed_vault_file(ROOT_VAULT, f"{target}.md", b"touch-back3-target\n")

    touch_page.goto(f"{ROOT_URL}/{origin}")
    expect_editor_contains(touch_page, "touch-back3-origin")

    touch_page.get_by_label("Open or create a note").tap()
    touch_page.get_by_placeholder(GO_TO).fill(target)
    row = touch_page.get_by_role("button", name=target)
    expect(row).to_be_visible()
    row.tap()
    expect(touch_page).to_have_url(re.compile(re.escape(target) + r"$"))

    touch_page.go_back()
    expect(touch_page).to_have_url(re.compile(re.escape(origin) + r"$"))


def test_delete_confirm_names_a_gesture_this_device_has(touch_page: Page, browser_name: str):
    """The armed row said "(Enter)" — a key a software keyboard cannot press.
    Tapping the armed row already deleted; only the label was wrong."""
    note = f"touch-del-{browser_name}/doomed"
    seed_vault_file(ROOT_VAULT, f"{note}.md", b"touch-delete-body\n")
    touch_page.goto(f"{ROOT_URL}/{note}")
    expect(touch_page.locator(".cm-content")).to_be_visible()

    touch_page.get_by_label("Delete a file").tap()
    touch_page.get_by_placeholder(PICK_FILE).fill(note)
    # `has_text=` substring match, not get_by_role(name=re.compile(...)): a
    # vault path contains "/", which Playwright reads as a regex delimiter in a
    # role selector and fails to parse.
    row = touch_page.locator("button", has_text=note).first
    expect(row).to_be_visible()
    row.tap()  # arms the confirmation

    armed = touch_page.get_by_text(re.compile(r"Confirm delete:"))
    expect(armed).to_be_visible()
    expect(armed).to_contain_text("tap again")
    expect(armed).not_to_contain_text("(Enter)")

    armed.tap()  # second tap deletes
    poll_until(lambda: read_vault_file(ROOT_VAULT, f"{note}.md") is None, timeout=20)
