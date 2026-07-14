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

from selenium.webdriver import ActionChains, Keys

from conftest import (
    ROOT_ALIAS,
    make_png,
    seed_vault_file,
    type_text,
    wait_for,
    wait_until,
)

BASE = f"http://{ROOT_ALIAS}:8000"


def _img_state(driver) -> dict | None:
    """src + decoded width of the rotating.png <img>, resolved in a single
    JS call — the AssetViewer remounts per navigation, so a Python-held
    element handle goes stale between find and measure."""
    return driver.execute_script(
        """
        for (const img of document.querySelectorAll('img')) {
          const src = img.getAttribute('src')
          if (src && src.includes('rotating.png')) {
            return { src, width: img.complete ? img.naturalWidth : null }
          }
        }
        return null
        """
    )


def _natural_width(driver) -> int | None:
    state = _img_state(driver)
    return state["width"] if state else None


def _switcher_goto(driver, path: str) -> None:
    ActionChains(driver).key_down(Keys.CONTROL).send_keys("k").key_up(
        Keys.CONTROL
    ).perform()
    if path:
        type_text(driver, path)
    ActionChains(driver).send_keys(Keys.ENTER).perform()


def test_overwritten_asset_shows_fresh_pixels_on_spa_navigation(driver, root_app):
    seed_vault_file(root_app, "viewer/rotating.png", make_png(1, 1))
    # Enter through the SPA: over plain HTTP (no Fetch Metadata) a DIRECT
    # nav to an image URL is served raw bytes and Chrome renders its own
    # image document — the AssetViewer only mounts on in-app navigation.
    driver.get(f"{BASE}/")
    wait_for(driver, ".cm-content")
    _switcher_goto(driver, "viewer/rotating.png")
    wait_until(driver, lambda: _natural_width(driver) == 1)
    first_src = _img_state(driver)["src"]
    assert "?v=" in first_src, "AssetViewer src must carry the cache-bust param"

    # the external writer replaces the image at the SAME path
    seed_vault_file(root_app, "viewer/rotating.png", make_png(2, 2))

    # hop home and back through the quick switcher — same document, so the
    # in-memory image cache is live and only the ?v= rotation defeats it
    _switcher_goto(driver, "")  # pinned `/` → home
    wait_for(driver, ".cm-content")
    _switcher_goto(driver, "viewer/rotating.png")

    wait_until(driver, lambda: _natural_width(driver) == 2, timeout=25)
    second_src = _img_state(driver)["src"]
    assert second_src != first_src, "cache-bust param must rotate per navigation"
