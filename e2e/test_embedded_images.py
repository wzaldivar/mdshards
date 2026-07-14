"""Embedded-image matrix: every supported `![alt](url)` path shape must
actually decode in the browser, at a root mount AND under BASE_URL=/wiki.

Shapes (resolved against the note `embeds/note.md`, per the vault-relative
resolution rule):
  - sibling            pic.png                  -> embeds/pic.png
  - subdirectory       sub/pic2.png             -> embeds/sub/pic2.png
  - parent traversal   ../shared/pic.png        -> shared/pic.png
  - root-absolute      /abs/pic3.png            -> abs/pic3.png
  - encoded spaces     ../my%20pics/my%20pic.png -> "my pics/my pic.png"
"""

import pytest
from selenium.webdriver.common.by import By

from conftest import (
    ROOT_ALIAS,
    SUBPATH_ALIAS,
    SUBPATH_PREFIX,
    TINY_PNG,
    seed_vault_file,
    wait_for,
    wait_until,
)

NOTE = b"""# embeds

![sibling](pic.png)

![subdir](sub/pic2.png)

![traversal](../shared/pic.png)

![absolute](/abs/pic3.png)

![spaces](../my%20pics/my%20pic.png)
"""

# vault file -> the path the browser must end up requesting (pre-prefix)
EXPECTED = {
    "embeds/pic.png": "/embeds/pic.png",
    "embeds/sub/pic2.png": "/embeds/sub/pic2.png",
    "shared/pic.png": "/shared/pic.png",
    "abs/pic3.png": "/abs/pic3.png",
    "my pics/my pic.png": "/my%20pics/my%20pic.png",
}


def _seed(app) -> None:
    for vault_path in EXPECTED:
        seed_vault_file(app, vault_path, TINY_PNG)
    seed_vault_file(app, "embeds/note.md", NOTE)


def _loaded_srcs(driver) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for img in driver.find_elements(By.CSS_SELECTOR, "img"):
        src = img.get_attribute("src")
        if not src:
            continue
        out[src] = driver.execute_script(
            "return arguments[0].complete && arguments[0].naturalWidth > 0", img
        )
    return out


@pytest.mark.parametrize("mount", ["root", "subpath"])
def test_all_embed_shapes_decode(driver, request, mount):
    if mount == "root":
        app = request.getfixturevalue("root_app")
        base, prefix = f"http://{ROOT_ALIAS}:8000", ""
    else:
        app = request.getfixturevalue("subpath_app")
        base = f"http://{SUBPATH_ALIAS}:8000{SUBPATH_PREFIX}"
        prefix = SUBPATH_PREFIX
    _seed(app)

    driver.get(f"{base}/embeds/note")
    wait_for(driver, ".cm-content")
    wait_until(
        driver,
        lambda: (
            len([ok for ok in _loaded_srcs(driver).values() if ok]) >= len(EXPECTED)
        ),
        timeout=25,
    )

    srcs = _loaded_srcs(driver)
    for expected in EXPECTED.values():
        want = prefix + expected
        matching = [s for s, ok in srcs.items() if s.endswith(want) and ok]
        assert matching, f"no decoded <img> for {want}; got {srcs}"
    # Nothing may escape the prefix under the sub-path mount.
    if prefix:
        escaped = [s for s in srcs if f"//{SUBPATH_ALIAS}:8000{prefix}" not in s]
        assert not escaped, f"embeds escaped the prefix: {escaped}"
