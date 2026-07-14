"""Real-browser e2e suite — Playwright, multi-engine, fully containerized.

Orchestration is docker compose (e2e/docker-compose.e2e.yml): the shipping
image runs as `app-root` and `app-wiki` (BASE_URL=/wiki) services, and this
test process runs inside the official Playwright image as the `tests` service
on the same network. Playwright drives Chromium / WebKit / Firefox — all
inside that container — against the apps by service name, which is exactly
what a browser reaching the app over a network sees. No host browser, no
Selenium grid.

The vault is a named volume shared between each app and this container, so the
external-writer role (seed/read/flush-poll) is a direct filesystem write on
the shared mount rather than a `docker exec`.

Run locally (needs a Docker daemon — colima):
    docker compose -f e2e/docker-compose.e2e.yml up --build \
        --abort-on-container-exit --exit-code-from tests
"""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

# URLs the browser (inside the tests container) uses to reach each app by its
# compose service name. WIKI_URL already carries the /wiki prefix.
ROOT_URL = os.environ.get("ROOT_URL", "http://app-root:8000")
WIKI_PREFIX = os.environ.get("WIKI_PREFIX", "/wiki")
WIKI_ORIGIN = os.environ.get("WIKI_URL", "http://app-wiki:8000")
WIKI_URL = WIKI_ORIGIN + WIKI_PREFIX
# host:port the browser addresses the sub-path app by — used to spot requests
# that escaped the prefix (origin-rooted rather than under /wiki).
WIKI_HOST = WIKI_ORIGIN.split("//", 1)[-1]
PERMS_URL = os.environ.get("PERMS_URL", "http://app-perms:8000")

# Each app's vault, seen through the shared named volume mounted into this
# container. The app writes /data/vault; we see it here.
ROOT_VAULT = Path(os.environ.get("ROOT_VAULT", "/vaults/root/vault"))
WIKI_VAULT = Path(os.environ.get("WIKI_VAULT", "/vaults/wiki/vault"))
PERMS_VAULT = Path(os.environ.get("PERMS_VAULT", "/vaults/perms-vault"))
PERMS_CACHE = Path(os.environ.get("PERMS_CACHE", "/vaults/perms-cache"))

# The app runs as this uid/gid (docker-entrypoint default). Seeded files must
# land under it so the app can rename/delete/rewrite them.
APP_UID = int(os.environ.get("APP_UID", "1000"))
APP_GID = int(os.environ.get("APP_GID", "1000"))

# expect() default is 5s; our flows (image decode, cold loads) want headroom.
expect.set_options(timeout=15_000)


# ---- readiness ----


def _wait_ready(base: str, timeout: float = 120) -> None:
    # Poll the SPA shell ("/"), NOT /api/* — the OriginGuard 403s a header-less
    # urllib request to /api (it looks like a non-browser caller), whereas a
    # safe GET to the shell passes the loose gate. A 200 there means uvicorn is
    # serving. `base` already carries any /wiki prefix.
    url = base.rstrip("/") + "/"
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status == 200:
                    return
        except (urllib.error.URLError, OSError) as e:
            last = e
        time.sleep(1)
    raise RuntimeError(f"app never became ready at {url}: {last}")


@pytest.fixture(scope="session", autouse=True)
def _apps_ready() -> None:
    _wait_ready(ROOT_URL)
    _wait_ready(WIKI_URL)


@pytest.fixture(scope="session")
def perms_ready() -> None:
    """Opt-in readiness for the split-mount permissions app — only the one
    infra test needs it, so it isn't in the autouse gate."""
    _wait_ready(PERMS_URL)


# ---- Playwright launch tweaks ----


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args, browser_name):  # noqa: ANN001
    # Chromium refuses to start as root without --no-sandbox; the tests
    # container is root (so it can chown seeded files to the app uid).
    if browser_name == "chromium":
        return {
            **browser_type_launch_args,
            "args": [*browser_type_launch_args.get("args", []), "--no-sandbox"],
        }
    return browser_type_launch_args


# ---- vault helpers (shared-volume external writer) ----


def _chown_to_app(root: Path) -> None:
    try:
        os.chown(root, APP_UID, APP_GID)
        for p in root.rglob("*"):
            os.chown(p, APP_UID, APP_GID)
    except PermissionError:
        # Running as the app uid already (not root) — nothing to hand over.
        pass


def seed_vault_file(vault: Path, rel_path: str, content: bytes) -> None:
    """Write a file into the vault as an EXTERNAL writer (the Syncthing /
    Obsidian role). We run as root in the tests image, so hand the whole vault
    to the app uid afterward — otherwise the unprivileged app 500s on
    rename/delete and its flush can't rewrite the file."""
    full = vault / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(content)
    _chown_to_app(vault)


def read_vault_file(vault: Path, rel_path: str) -> str | None:
    p = vault / rel_path
    try:
        return p.read_text()
    except (FileNotFoundError, IsADirectoryError):
        return None


def wait_vault_file(vault: Path, rel_path: str, contains: str, timeout: float = 20) -> str:
    """Poll the vault until `rel_path` exists and contains the marker — the
    CRDT layer flushes asynchronously, so give it a moment."""
    deadline = time.monotonic() + timeout
    last: str | None = None
    while time.monotonic() < deadline:
        last = read_vault_file(vault, rel_path)
        if last is not None and contains in last:
            return last
        time.sleep(0.5)
    raise AssertionError(
        f"vault file {rel_path!r} never contained {contains!r}; last read: {last!r}"
    )


# ---- polling ----


def poll_until(predicate, timeout: float = 15, interval: float = 0.25) -> None:
    """Poll a Python predicate to truthiness. For assertions Playwright's
    locator matchers can't express (e.g. comparing two computed styles).
    Prefer expect()/wait_for_function for DOM state; use this only when the
    check must run in Python."""
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except Exception as e:  # noqa: BLE001 - transient DOM races are expected
            last_exc = e
        time.sleep(interval)
    raise AssertionError(f"condition not met within {timeout}s; last exception: {last_exc}")


# ---- editor helpers ----


def click_editor(page: Page) -> None:
    page.locator(".cm-content").click()


def type_text(page: Page, text: str) -> None:
    page.keyboard.type(text)


def editor_text(page: Page) -> str:
    return page.locator(".cm-content").inner_text()


# ---- fixtures assets ----


def make_png(width: int, height: int) -> bytes:
    """Minimal valid RGBA PNG of the given dimensions, stdlib only — tests
    tell images apart by naturalWidth, not color. Must be a byte-valid PNG:
    Firefox's decoder is stricter than Blink/WebKit and reports naturalWidth 0
    (a broken image) for a malformed stream that the others tolerate."""
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff\x00\x00\xff" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


# 1x1 red PNG — enough for the browser to decode and report naturalWidth > 0.
# Generated (not a hand-rolled blob) so all three engines accept it.
TINY_PNG = make_png(1, 1)
