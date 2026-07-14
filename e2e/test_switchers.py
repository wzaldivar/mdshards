"""Keyboard-first switcher journeys — real browser, real container.

These are the shortcuts that have regressed repeatedly (Cmd/Ctrl-K quick
switcher, Ctrl-Shift-K rename, Ctrl-Backspace delete, Ctrl-E emoji), so each
is driven end to end here: the chord fires, the modal opens, its core action
lands (navigation / disk write / deletion). The last test guards the fragile
case specifically — a shortcut fired while focus is inside the AssetViewer's
iframe (an asset URL), which relies on the per-iframe shortcut rebind.

The shell + list-nav were deduplicated into SwitcherShell / useListNavigation;
these journeys pin that the shared chrome still behaves per switcher.

Chords go through the window-level binding, so ActionChains (active element)
is right for them; text and Enter/Escape are sent to the located input
element directly, so they can't be lost to a focus race in the container.
Linux-container Chromium maps the app's Cmd/Ctrl bindings to CONTROL.
"""

from selenium.webdriver import ActionChains, Keys
from selenium.webdriver.common.by import By

from conftest import (
    ROOT_ALIAS,
    click_editor,
    editor_text,
    read_vault_file,
    seed_vault_file,
    wait_for,
    wait_until,
    wait_vault_file,
)

BASE = f"http://{ROOT_ALIAS}:8000"


# ---- chord + modal helpers ----


def _chord(driver, key, *, shift=False) -> None:
    """Fire a global Ctrl(+Shift) shortcut — caught by the window-level
    keydown binding, so it doesn't matter which element has focus."""
    ac = ActionChains(driver).key_down(Keys.CONTROL)
    if shift:
        ac = ac.key_down(Keys.SHIFT)
    ac = ac.send_keys(key)
    if shift:
        ac = ac.key_up(Keys.SHIFT)
    ac.key_up(Keys.CONTROL).perform()


def _switcher_open(driver, prefix: str):
    """Wait until the switcher whose input placeholder starts with `prefix`
    is mounted. Identified by placeholder — stable across the CSS-module
    hashing that scrambles class names."""
    return wait_for(driver, f"input[placeholder^='{prefix}']")


def _send(driver, prefix: str, *keys) -> None:
    """Send keys to the switcher input, re-locating it fresh each call.
    The input is a controlled React field that re-renders on every state
    change, so a held element handle goes stale between actions; re-finding
    right before use avoids StaleElementReferenceException. `send_keys` also
    focuses the element, so no separate click is needed."""
    driver.find_element(By.CSS_SELECTOR, f"input[placeholder^='{prefix}']").send_keys(*keys)


def _switcher_gone(driver, prefix: str) -> None:
    wait_until(
        driver,
        lambda: not driver.find_elements(By.CSS_SELECTOR, f"input[placeholder^='{prefix}']"),
    )


def _body_text(driver) -> str:
    return driver.find_element(By.TAG_NAME, "body").text


# ---- quick switcher (Ctrl-K) ----


def test_quick_switcher_navigates_to_existing_note(driver, root_app):
    seed_vault_file(root_app, "swq/target.md", b"swq-target-body\n")
    driver.get(f"{BASE}/")
    wait_for(driver, ".cm-content")

    _chord(driver, "k")
    _switcher_open(driver, "Go to")
    _send(driver, "Go to", "swq/target")
    # best-match highlight lands on the typed path; plain Enter navigates
    wait_until(driver, lambda: "swq/target" in _body_text(driver))
    _send(driver, "Go to", Keys.ENTER)

    wait_until(driver, lambda: driver.current_url.endswith("/swq/target"))
    wait_until(driver, lambda: "swq-target-body" in editor_text(driver))


def test_quick_switcher_escape_closes_and_stays_put(driver, root_app):
    driver.get(f"{BASE}/")
    wait_for(driver, ".cm-content")
    _chord(driver, "k")
    _switcher_open(driver, "Go to")
    _send(driver, "Go to", Keys.ESCAPE)
    _switcher_gone(driver, "Go to")
    assert driver.current_url.rstrip("/") == BASE


# ---- delete switcher (Ctrl-Backspace) ----


def test_delete_switcher_confirms_then_deletes_current_and_navigates_home(driver, root_app):
    seed_vault_file(root_app, "swd/victim.md", b"swd-victim-body\n")
    driver.get(f"{BASE}/swd/victim")
    wait_for(driver, ".cm-content")
    wait_until(driver, lambda: "swd-victim-body" in editor_text(driver))

    _chord(driver, Keys.BACKSPACE)
    _switcher_open(driver, "Pick a file")
    # top entry "Delete this file (swd/victim)" is preselected; first Enter arms
    _send(driver, "Pick a file", Keys.ENTER)
    wait_until(driver, lambda: "confirm delete" in _body_text(driver).lower())
    # second Enter commits the delete
    _send(driver, "Pick a file", Keys.ENTER)

    # deleting the file being viewed navigates home and removes it from disk
    wait_until(driver, lambda: driver.current_url.rstrip("/") == BASE)
    wait_until(driver, lambda: read_vault_file(root_app, "swd/victim.md") is None)


# ---- rename switcher (Ctrl-Shift-K) ----


def test_rename_switcher_moves_note_and_navigates(driver, root_app):
    seed_vault_file(root_app, "swr/old.md", b"swr-rename-body\n")
    driver.get(f"{BASE}/swr/old")
    wait_for(driver, ".cm-content")
    wait_until(driver, lambda: "swr-rename-body" in editor_text(driver))

    _chord(driver, "k", shift=True)
    _switcher_open(driver, "Rename to")
    # prefilled with the current doc-id — select-all then type to replace it
    _send(driver, "Rename to", Keys.CONTROL, "a")
    _send(driver, "Rename to", "swr/new")
    _send(driver, "Rename to", Keys.ENTER)

    wait_until(driver, lambda: driver.current_url.endswith("/swr/new"))
    wait_vault_file(root_app, "swr/new.md", "swr-rename-body")
    assert read_vault_file(root_app, "swr/old.md") is None


# ---- emoji picker (Ctrl-E) ----


def test_emoji_picker_inserts_shortcode(driver, root_app):
    seed_vault_file(root_app, "swe/note.md", b"emoji-seed \n")
    driver.get(f"{BASE}/swe/note")
    wait_for(driver, ".cm-content")
    click_editor(driver)  # a live buffer + cursor for the insert

    _chord(driver, "e")
    _switcher_open(driver, "Insert emoji")
    _send(driver, "Insert emoji", "smile")
    # wait for the (lazily bundled) gemoji dataset to load and rank a match
    wait_until(driver, lambda: ":smile:" in _body_text(driver))
    _send(driver, "Insert emoji", Keys.ENTER)

    # the FILE keeps the literal shortcode; the glyph is render-time only
    wait_vault_file(root_app, "swe/note.md", ":smile:")


# ---- asset-URL context: the shortcut rebind inside the AssetViewer iframe ----


def test_shortcut_fires_from_inside_asset_iframe(driver, root_app):
    """A text asset renders in a same-origin iframe that re-binds the global
    shortcuts on its contentDocument. With focus inside that iframe, Ctrl-K
    must still open the quick switcher — the 'works on asset URLs too' rule
    that broke before. Reached via in-app nav (a direct HTTP hit to an asset
    URL yields Chrome's native viewer, not the AssetViewer)."""
    seed_vault_file(root_app, "swa/readme.txt", b"asset-iframe-body\n")
    driver.get(f"{BASE}/")
    wait_for(driver, ".cm-content")

    # in-app nav through the quick switcher mounts the AssetViewer
    _chord(driver, "k")
    _switcher_open(driver, "Go to")
    _send(driver, "Go to", "swa/readme.txt")
    wait_until(driver, lambda: "swa/readme.txt" in _body_text(driver))
    _send(driver, "Go to", Keys.ENTER)

    frame = wait_for(driver, "iframe")
    driver.switch_to.frame(frame)
    # focus goes into the iframe's document — the window binding no longer
    # sees the keydown; only the rebind on contentDocument does
    driver.find_element(By.TAG_NAME, "body").click()
    _chord(driver, "k")
    driver.switch_to.default_content()

    _switcher_open(driver, "Go to")

