"""Regression: overwritten images must show fresh pixels (c0d3d5b, e804d4e).

Browsers reuse already-DECODED images by URL for the lifetime of the SPA's
document without revalidating — Cache-Control can't help — so after an
upload/external write replaced an asset at the same path, a same-URL <img>
kept rendering the old pixels. The fix: AssetViewer remounts per navigation
and cache-busts its rendered src with a per-navigation `?v=` param.

The failing path is same-document SPA navigation (a full page load would
mask the bug behind HTTP revalidation), so this journey hops away and back
through the quick switcher, never reloading the document.
"""

import re

from playwright.sync_api import Page, expect

from conftest import ROOT_URL, ROOT_VAULT, make_png, poll_until, seed_vault_file


def _img_state(page: Page) -> dict | None:
    """src + decoded width of the rotating.png <img>, resolved in a single
    JS call — the AssetViewer remounts per navigation, so a Python-held
    handle would go stale between find and measure."""
    return page.evaluate(
        """
        () => {
          for (const img of document.querySelectorAll('img')) {
            const src = img.getAttribute('src')
            if (src && src.includes('rotating.png')) {
              return { src, width: img.complete ? img.naturalWidth : null }
            }
          }
          return null
        }
        """
    )


def _natural_width(page: Page) -> int | None:
    state = _img_state(page)
    return state["width"] if state else None


def _switcher_goto(page: Page, path: str) -> None:
    page.keyboard.press("Control+k")
    switcher = page.get_by_placeholder(re.compile("go to or create", re.I))
    if path:
        switcher.fill(path)
        # wait for the async tree fetch to surface (and select) the row, else
        # plain Enter fires against an empty match list and no-ops. Home ("")
        # rides the always-pinned index row, so it needs no wait.
        expect(page.get_by_role("button", name=path)).to_be_visible()
    switcher.press("Enter")


def test_overwritten_asset_shows_fresh_pixels_on_spa_navigation(page: Page):
    seed_vault_file(ROOT_VAULT, "viewer/rotating.png", make_png(1, 1))
    # Enter through the SPA: over plain HTTP (no Fetch Metadata) a DIRECT
    # nav to an image URL is served raw bytes and the browser renders its own
    # image document — the AssetViewer only mounts on in-app navigation.
    page.goto(f"{ROOT_URL}/")
    expect(page.locator(".cm-content")).to_be_visible()
    _switcher_goto(page, "viewer/rotating.png")
    poll_until(lambda: _natural_width(page) == 1, timeout=20)
    first_src = _img_state(page)["src"]
    assert "?v=" in first_src, "AssetViewer src must carry the cache-bust param"

    # the external writer replaces the image at the SAME path
    seed_vault_file(ROOT_VAULT, "viewer/rotating.png", make_png(2, 2))

    # hop home and back through the quick switcher — same document, so the
    # in-memory image cache is live and only the ?v= rotation defeats it
    _switcher_goto(page, "")  # pinned `/` → home
    expect(page.locator(".cm-content")).to_be_visible()
    _switcher_goto(page, "viewer/rotating.png")

    poll_until(lambda: _natural_width(page) == 2, timeout=25)
    second_src = _img_state(page)["src"]
    assert second_src != first_src, "cache-bust param must rotate per navigation"
