"""Regression: split bind mounts with host ownership must not lose writes.

The compose shape users actually write mounts the vault and cache separately
(`/host/vault:/data/vault`, `./cache:/data/cache`), leaving `/data` itself as
the image layer. The entrypoint's chown guard used to check only `/data` —
already owned by app — so the nested mounts kept host ownership (NAS uid,
docker-created root dirs), every flush raised PermissionError inside the flush
task where it was never retrieved, and edits vanished silently behind a
healthy-looking editor.

Here the `app-perms` compose service boots on volumes that `perm-seed` made
root-owned first (a NAS export / docker-created dir with a preexisting note);
this journey edits through a real browser and requires both the vault write
and the .yjs cache to land, plus the entrypoint to have remapped ownership.

Pure infrastructure — engine-agnostic — so it runs on Chromium only.
"""

import os

import pytest
from playwright.sync_api import Page

from conftest import (
    APP_UID,
    PERMS_CACHE,
    PERMS_URL,
    PERMS_VAULT,
    click_editor,
    poll_until,
    type_text,
    wait_vault_file,
)


def test_edits_flush_despite_host_owned_mounts(page: Page, browser_name: str, perms_ready):
    if browser_name != "chromium":
        pytest.skip("infra/permissions test is engine-agnostic — Chromium only")

    page.goto(f"{PERMS_URL}/")
    click_editor(page)
    marker = "perm-mount-roundtrip"
    type_text(page, marker + " ")
    # the vault write must land...
    wait_vault_file(PERMS_VAULT, "index.md", marker)
    # ...and the CRDT cache too (it was the first casualty of the root-owned
    # ./cache dir — and its failure used to take the vault flush down with it)
    poll_until(lambda: any(PERMS_CACHE.rglob("*.yjs")), timeout=20)
    # the entrypoint remapped ownership of both mounts to the app uid
    assert os.stat(PERMS_VAULT).st_uid == APP_UID, "vault mount not remapped to app uid"
    assert os.stat(PERMS_CACHE).st_uid == APP_UID, "cache mount not remapped to app uid"
