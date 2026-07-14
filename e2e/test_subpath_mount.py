"""Sub-path mount (BASE_URL=/wiki) journeys — the full-containment contract.

The browser talks straight to the container using prefixed URLs, which is
byte-for-byte what a prefix-preserving proxy (the documented single
PathPrefix rule) would forward.
"""

from selenium.webdriver import ActionChains, Keys
from selenium.webdriver.common.by import By

from conftest import (
    SUBPATH_ALIAS,
    SUBPATH_PREFIX,
    TINY_PNG,
    click_editor,
    seed_vault_file,
    type_text,
    wait_for,
    wait_until,
    wait_vault_file,
)

BASE = f"http://{SUBPATH_ALIAS}:8000{SUBPATH_PREFIX}"


def test_shell_is_contained_under_prefix(driver, subpath_app):
    """The served shell carries the home-path meta and prefixed bundle refs,
    and NOTHING the page subsequently loads escapes the prefix."""
    driver.get(f"{BASE}/")
    wait_for(driver, ".cm-content")
    meta = driver.find_elements(By.CSS_SELECTOR, 'meta[name="mdshards-home-path"]')
    assert meta and meta[0].get_attribute("content") == SUBPATH_PREFIX
    requests = driver.execute_script(
        "return performance.getEntriesByType('resource').map(e => e.name)"
    )
    origin_rooted = [
        u
        for u in requests
        if f"//{SUBPATH_ALIAS}:8000" in u
        and f"//{SUBPATH_ALIAS}:8000{SUBPATH_PREFIX}" not in u
    ]
    assert not origin_rooted, f"requests escaped the prefix: {origin_rooted}"


def test_edits_persist_under_prefix(driver, subpath_app):
    driver.get(f"{BASE}/")
    click_editor(driver)
    marker = "e2e-wiki-roundtrip"
    type_text(driver, marker + " ")
    wait_vault_file(subpath_app, "index.md", marker)


def test_note_with_image_renders_under_prefix(driver, subpath_app):
    """The 1.2.0 regression guard: in-note images must load at a sub-path
    mount with no extra proxy rules."""
    seed_vault_file(subpath_app, "gallery/pic.png", TINY_PNG)
    seed_vault_file(subpath_app, "gallery/note.md", b"# gallery\n\n![p](pic.png)\n")
    driver.get(f"{BASE}/gallery/note")
    wait_for(driver, ".cm-content")
    wait_until(
        driver,
        lambda: any(
            img.get_attribute("src")
            and driver.execute_script(
                "return arguments[0].complete && arguments[0].naturalWidth > 0", img
            )
            for img in driver.find_elements(By.CSS_SELECTOR, "img")
        ),
    )
    loaded = [
        img.get_attribute("src")
        for img in driver.find_elements(By.CSS_SELECTOR, "img")
        if img.get_attribute("src")
    ]
    assert any(f"{SUBPATH_PREFIX}/gallery/pic.png" in src for src in loaded), loaded


def test_vault_path_starting_with_prefix_segment(driver, subpath_app):
    """A vault path whose first segment equals the mount segment: creating
    `wiki/foo` under BASE_URL=/wiki must be browsable at /wiki/wiki/foo —
    the prefix is applied once client-side and stripped once server-side."""
    driver.get(f"{BASE}/")
    click_editor(driver)
    ActionChains(driver).key_down(Keys.CONTROL).send_keys("k").key_up(
        Keys.CONTROL
    ).perform()
    type_text(driver, "wiki/foo")
    ActionChains(driver).key_down(Keys.SHIFT).send_keys(Keys.ENTER).key_up(
        Keys.SHIFT
    ).perform()
    wait_until(
        driver,
        lambda: driver.current_url.endswith(f"{SUBPATH_PREFIX}/wiki/foo"),
    )
    click_editor(driver)
    marker = "shadow-segment-note"
    type_text(driver, marker)
    wait_vault_file(subpath_app, "wiki/foo.md", marker)

    # …and it survives a cold reload at the double-segment URL.
    driver.get(f"{BASE}/wiki/foo")
    wait_until(driver, lambda: marker in (wait_for(driver, ".cm-content").text or ""))
