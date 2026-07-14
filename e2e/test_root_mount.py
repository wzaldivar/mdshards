"""Root-mount (no BASE_URL) journeys — deployment mode 1 as shipped."""

from selenium.webdriver import ActionChains, Keys
from selenium.webdriver.common.by import By

from conftest import (
    ROOT_ALIAS,
    TINY_PNG,
    click_editor,
    seed_vault_file,
    type_text,
    wait_for,
    wait_until,
    wait_vault_file,
)

BASE = f"http://{ROOT_ALIAS}:8000"


def test_home_loads_and_edits_persist_to_disk(driver, root_app):
    """The core loop: browse /, the CRDT editor mounts, typed text lands in
    the on-disk index.md — server-is-source-of-truth verified end to end."""
    driver.get(f"{BASE}/")
    click_editor(driver)
    marker = "e2e-root-roundtrip"
    type_text(driver, marker + " ")
    wait_vault_file(root_app, "index.md", marker)


def test_note_with_image_renders(driver, root_app):
    """An externally-written note embedding an externally-written image —
    the image must actually decode in the browser (naturalWidth > 0), not
    merely produce an <img> tag."""
    seed_vault_file(root_app, "gallery/pic.png", TINY_PNG)
    seed_vault_file(root_app, "gallery/note.md", b"# gallery\n\n![p](pic.png)\n")
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
    assert any(src.endswith("/gallery/pic.png") for src in loaded), loaded


def test_quick_switcher_creates_note(driver, root_app):
    """Cmd/Ctrl-K, type a fresh path, Shift-Enter: the ONLY UI surface that
    creates files implicitly — must create parents and navigate there."""
    driver.get(f"{BASE}/")
    click_editor(driver)
    ActionChains(driver).key_down(Keys.CONTROL).send_keys("k").key_up(
        Keys.CONTROL
    ).perform()
    type_text(driver, "created/by-e2e")
    ActionChains(driver).key_down(Keys.SHIFT).send_keys(Keys.ENTER).key_up(
        Keys.SHIFT
    ).perform()
    wait_until(driver, lambda: driver.current_url.endswith("/created/by-e2e"))
    click_editor(driver)
    marker = "created-note-content"
    type_text(driver, marker)
    wait_vault_file(root_app, "created/by-e2e.md", marker)


def test_missing_path_renders_notfound_view(driver, root_app):
    """A typo'd URL serves the SPA shell and the React NotFound view — the
    'missing paths serve the shell' rule, browser-observed."""
    driver.get(f"{BASE}/no/such/note")
    wait_until(
        driver,
        lambda: "not found" in driver.find_element(By.TAG_NAME, "body").text.lower(),
    )
