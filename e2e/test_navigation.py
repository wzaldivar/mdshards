"""Navigation regressions — the read-only "dino" banner must belong to the
CURRENT editor only.

Leaving note A unmounts its editor and closes its WebSocket on a LATER task;
a bug that has regressed twice let that late close re-arm the ~grace-second
read-only countdown as a zombie no teardown cancelled — it then fired on
whatever note you'd since opened, stranding a false "connection lost" dino on
note B. This drives A→B (and back) and asserts no dino appears within a full
countdown window, with note B still live and editable.

Runs against `app-dino`, which sets a short GRACE_PERIOD_SECONDS so the
countdown (and thus any zombie) fires in seconds instead of the 30s default.
Engine-unique note paths keep the shared vault from colliding across the
Chromium/Firefox/WebKit matrix.
"""

import re

from playwright.sync_api import Page, expect

from conftest import DINO_URL, DINO_VAULT, expect_editor_contains, seed_vault_file

GO_TO = re.compile("go to or create", re.I)
DINO = re.compile("lost connection", re.I)


def _quick_nav(page: Page, target: str) -> None:
    page.keyboard.press("Control+k")
    switcher = page.get_by_placeholder(GO_TO)
    switcher.fill(target)
    # Wait for the async tree fetch to surface (and select) the match before
    # Enter, or it fires against an empty list and no-ops.
    expect(page.get_by_role("button", name=target)).to_be_visible()
    switcher.press("Enter")


def test_navigating_between_notes_leaves_no_stranded_dino(page: Page, browser_name: str):
    a, b = f"nav/a-{browser_name}", f"nav/b-{browser_name}"
    seed_vault_file(DINO_VAULT, f"{a}.md", b"note-a-body\n")
    seed_vault_file(DINO_VAULT, f"{b}.md", b"note-b-body\n")

    page.goto(f"{DINO_URL}/{a}")
    expect_editor_contains(page, "note-a-body")

    # Leave A for B. A's editor unmounts and closes its WebSocket on a later
    # task — the exact trigger that used to arm a zombie read-only countdown.
    _quick_nav(page, b)
    expect(page).to_have_url(re.compile(rf"/{re.escape(b)}$"))
    expect_editor_contains(page, "note-b-body")

    # Wait out a full read-only countdown (grace is ~2s on app-dino) plus margin.
    # A zombie armed by A's teardown would surface the dino on B right here.
    page.wait_for_timeout(6000)
    expect(page.get_by_text(DINO)).to_have_count(0)
    # Note B is genuinely live, not stranded read-only.
    expect_editor_contains(page, "note-b-body")
