"""Entering a note focuses the editor — you can start typing without a click.

The CodeMirror view is rebuilt on every note open; without an explicit
focus the caret sat outside the buffer and the first keystrokes went nowhere.
These journeys never click the editor: they open a note (by direct load and
by the quick switcher, the two ways a desktop user enters one), type, and
assert the keystrokes reached disk through the CRDT. Engine-unique note paths
keep the shared vault from colliding across the Chromium/Firefox/WebKit matrix.
"""

import re

from playwright.sync_api import Page, expect

from conftest import (
    ROOT_URL,
    ROOT_VAULT,
    expect_editor_contains,
    quick_switch,
    seed_vault_file,
    wait_vault_file,
)


def test_direct_load_focuses_the_editor(page: Page, browser_name: str):
    note = f"focus/direct-{browser_name}"
    seed_vault_file(ROOT_VAULT, f"{note}.md", b"direct-body\n")

    page.goto(f"{ROOT_URL}/{note}")
    expect_editor_contains(page, "direct-body")
    expect(page.locator(".cm-content")).to_be_focused()

    page.keyboard.type("typed-on-load ")
    wait_vault_file(ROOT_VAULT, f"{note}.md", "typed-on-load")


def test_quick_switch_focuses_the_destination_editor(page: Page, browser_name: str):
    """The switcher's input holds focus until it closes; the destination
    editor must take it over rather than leave focus on the page body."""
    a, b = f"focus/from-{browser_name}", f"focus/to-{browser_name}"
    seed_vault_file(ROOT_VAULT, f"{a}.md", b"from-body\n")
    seed_vault_file(ROOT_VAULT, f"{b}.md", b"to-body\n")

    page.goto(f"{ROOT_URL}/{a}")
    expect_editor_contains(page, "from-body")

    quick_switch(page, b)
    expect(page).to_have_url(re.compile(rf"/{re.escape(b)}$"))
    expect_editor_contains(page, "to-body")
    expect(page.locator(".cm-content")).to_be_focused()

    page.keyboard.type("typed-after-switch ")
    wait_vault_file(ROOT_VAULT, f"{b}.md", "typed-after-switch")
