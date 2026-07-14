"""FEATURES.md rendering matrix — every SUPPORTED markdown syntax must
produce its rendered form in a real browser, not just parse.

Assertions favor what a user sees: markup characters hidden (the live-
preview contract), computed styles applied (bold weight, strike-through,
heading size), stable decoration classes (`cm-md-*`), and real widgets
(table grid, task checkboxes, emoji glyphs).

Every seeded note starts with a plain first line: the cursor lands at
position 0 on load and the touch convention keeps the touched line raw —
feature lines live below it.

Runs at the root mount; URL-shape independence across mounts is proven by
the embedded-image matrix, and the rendering pipeline is mount-agnostic.
"""

from selenium.webdriver.common.by import By

from conftest import ROOT_ALIAS, seed_vault_file, wait_for, wait_until

BASE = f"http://{ROOT_ALIAS}:8000"


def _open(driver, app, name: str, body: str):
    seed_vault_file(app, f"features/{name}.md", ("intro line\n\n" + body).encode())
    driver.get(f"{BASE}/features/{name}")
    wait_for(driver, ".cm-content")


def _lines(driver) -> list[str]:
    return driver.execute_script(
        "return [...document.querySelectorAll('.cm-line')].map(l => l.innerText)"
    )


def _visible_text(driver) -> str:
    return driver.execute_script(
        "return document.querySelector('.cm-content').innerText"
    )


def _style_of_text(driver, needle: str) -> dict:
    """Computed style of the deepest element whose text contains `needle`.
    Walks ALL elements (not just spans — table cells render real <strong>/
    <del> nodes) in document order, keeping the last match: parents precede
    children, so the survivor is the innermost element of the last
    occurrence — the one whose computed style the user actually sees."""
    return driver.execute_script(
        """
        const needle = arguments[0]
        let el = null
        for (const cand of document.querySelectorAll('.cm-content *')) {
          if (cand.textContent.includes(needle)) el = cand
        }
        if (!el) return null
        const cs = getComputedStyle(el)
        return {
          fontWeight: cs.fontWeight,
          fontStyle: cs.fontStyle,
          fontSize: parseFloat(cs.fontSize),
          textDecoration: cs.textDecorationLine,
          verticalAlign: cs.verticalAlign,
          color: cs.color,
        }
        """,
        needle,
    )


def test_inline_emphasis_and_marks(driver, root_app):
    _open(
        driver,
        root_app,
        "inline",
        "plain sentence\n\n"
        "**boldword** and *italword* and ***bolditalword*** and ~~struckword~~\n\n"
        "`codeword` and ==markedword== and H~2~O and X^2^ and last_charged_at\n\n"
        r"escaped \*not-em\* stays literal",
    )
    wait_until(driver, lambda: "boldword" in _visible_text(driver))
    text = _visible_text(driver)

    # live preview hides the markup characters
    for marker in ("**", "~~", "==", "`"):
        assert marker not in text, f"{marker!r} still visible:\n{text}"

    assert int(_style_of_text(driver, "boldword")["fontWeight"]) >= 600
    assert _style_of_text(driver, "italword")["fontStyle"] == "italic"
    boldital = _style_of_text(driver, "bolditalword")
    assert int(boldital["fontWeight"]) >= 600 and boldital["fontStyle"] == "italic"
    assert "line-through" in _style_of_text(driver, "struckword")["textDecoration"]

    # extended inline: highlight / sub / sup carry their stable classes
    assert driver.find_elements(By.CSS_SELECTOR, ".cm-md-mark")
    assert _style_of_text(driver, "2")  # smoke: spans exist at all
    assert driver.find_elements(By.CSS_SELECTOR, ".cm-md-sub")
    assert driver.find_elements(By.CSS_SELECTOR, ".cm-md-sup")

    # intra-word underscores stay literal (GFM rule)
    assert "last_charged_at" in text
    # escapes render the punctuation, not the backslash
    assert "*not-em*" in text and r"\*" not in text


def test_headings_render_larger_with_marks_hidden(driver, root_app):
    _open(
        driver,
        root_app,
        "headings",
        "# Alpha Heading\n\nbody paragraph\n\nSetext Heading\n===\n",
    )
    wait_until(driver, lambda: "Alpha Heading" in _visible_text(driver))
    text = _visible_text(driver)
    assert "# Alpha" not in text, "ATX marker still visible"
    body_size = _style_of_text(driver, "body paragraph")["fontSize"]
    assert _style_of_text(driver, "Alpha Heading")["fontSize"] > body_size
    assert _style_of_text(driver, "Setext Heading")["fontSize"] > body_size


def test_blocks_lists_quote_hr_and_code(driver, root_app):
    _open(
        driver,
        root_app,
        "blocks",
        "> quoted wisdom\n\n"
        "- first item\n- second item\n  - nested item\n\n"
        "1. ordered one\n2. ordered two\n\n"
        "---\n\n"
        "```python\ndef fenced_fn():\n    return 42\n```\n",
    )
    wait_until(driver, lambda: "quoted wisdom" in _visible_text(driver))
    text = _visible_text(driver)
    for expected in (
        "quoted wisdom",
        "first item",
        "nested item",
        "ordered one",
        "fenced_fn",
    ):
        assert expected in text
    # HR line gets its stable class
    assert driver.find_elements(By.CSS_SELECTOR, ".cm-md-hr")
    # syntax highlighting: the `def` keyword is colored differently from
    # plain body text (catppuccin token style applied)
    wait_until(
        driver,
        lambda: (
            _style_of_text(driver, "def")
            and _style_of_text(driver, "def")["color"]
            != _style_of_text(driver, "quoted wisdom")["color"]
        ),
    )


def test_task_lists_render_checkboxes(driver, root_app):
    _open(driver, root_app, "tasks", "- [x] done thing\n- [ ] pending thing\n")
    wait_until(
        driver,
        lambda: len(driver.find_elements(By.CSS_SELECTOR, "input[type=checkbox]")) >= 2,
    )
    boxes = driver.find_elements(By.CSS_SELECTOR, "input[type=checkbox]")
    checked = [b for b in boxes if b.is_selected()]
    assert len(checked) == 1, "exactly the [x] item should be checked"


def test_links_autolinks_and_reference_links(driver, root_app):
    _open(
        driver,
        root_app,
        "links",
        '[titled link](https://example.com "hover text")\n\n'
        "<https://autolink.example.com>\n\n"
        "[ref style][lbl]\n\n"
        "[lbl]: https://ref.example.com\n",
    )
    wait_until(driver, lambda: "titled link" in _visible_text(driver))
    text = _visible_text(driver)
    # inline link URL is hidden; the label is decorated and titled
    assert "(https://example.com" not in text
    links = {
        el.get_attribute("data-href"): el
        for el in driver.find_elements(By.CSS_SELECTOR, ".cm-md-link")
    }
    assert "https://example.com" in links
    assert links["https://example.com"].get_attribute("title") == "hover text"
    # reference form resolves through its label definition
    assert "https://ref.example.com" in links
    # autolink text stays visible (clickable URL)
    assert "https://autolink.example.com" in text


def test_tables_render_as_grid_except_cursor_row(driver, root_app):
    _open(
        driver,
        root_app,
        "table",
        "| Name | Value |\n| --- | --- |\n| **bold cell** | `code cell` |\n",
    )
    wait_until(
        driver,
        lambda: driver.find_elements(By.CSS_SELECTOR, ".cm-md-table-row"),
    )
    cells = [c.text for c in driver.find_elements(By.CSS_SELECTOR, ".cm-md-table-cell")]
    assert "Name" in cells and "bold cell" in cells and "code cell" in cells
    # separator row collapses to the stripe widget
    assert driver.find_elements(By.CSS_SELECTOR, ".cm-md-table-separator")
    # in-cell formatting is applied, marks hidden
    assert int(_style_of_text(driver, "bold cell")["fontWeight"]) >= 600
    assert "**" not in _visible_text(driver)


def test_emoji_shortcodes_render_glyphs(driver, root_app):
    _open(driver, root_app, "emoji", "shipping :t-rex: and :+1: today\n")
    wait_until(
        driver,
        lambda: len(driver.find_elements(By.CSS_SELECTOR, ".cm-md-emoji")) >= 2,
    )
    glyphs = [el.text for el in driver.find_elements(By.CSS_SELECTOR, ".cm-md-emoji")]
    assert "🦖" in glyphs and "👍" in glyphs
    assert ":t-rex:" not in _visible_text(driver)
    # the FILE keeps the literal shortcodes — glyphs are render-time only
    code, raw = root_app.exec(["cat", "/data/vault/features/emoji.md"])
    assert code == 0 and b":t-rex:" in raw and b":+1:" in raw


def test_wikilinks_render_and_navigate(driver, root_app):
    seed_vault_file(root_app, "features/target.md", b"wikilink landing pad\n")
    _open(
        driver,
        root_app,
        "wiki",
        "go to [[features/target]] or [[features/target|the alias]]\n",
    )
    wait_until(
        driver,
        lambda: len(driver.find_elements(By.CSS_SELECTOR, ".cm-md-wikilink")) >= 2,
    )
    text = _visible_text(driver)
    assert "[[" not in text, "wikilink brackets still visible"
    assert "the alias" in text
    assert "|" not in text.split("or")[1], "alias form must hide the target"
    # clicking navigates via the SPA router to the target note
    driver.find_elements(By.CSS_SELECTOR, ".cm-md-wikilink")[0].click()
    wait_until(driver, lambda: driver.current_url.endswith("/features/target"))
    wait_until(driver, lambda: "wikilink landing pad" in _visible_text(driver))


def test_asset_viewer_renders_direct_image_url(driver, root_app):
    from conftest import TINY_PNG

    seed_vault_file(root_app, "viewer/solo.png", TINY_PNG)
    driver.get(f"{BASE}/viewer/solo.png")
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
