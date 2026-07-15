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

import re

from playwright.sync_api import Page, expect

from conftest import (
    ROOT_URL,
    ROOT_VAULT,
    click_editor,
    poll_until,
    read_vault_file,
    seed_vault_file,
)

_STYLE_JS = """
(needle) => {
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
}
"""


def _open(page: Page, name: str, body: str) -> None:
    seed_vault_file(ROOT_VAULT, f"features/{name}.md", ("intro line\n\n" + body).encode())
    page.goto(f"{ROOT_URL}/features/{name}")
    expect(page.locator(".cm-content")).to_be_visible()


def _visible_text(page: Page) -> str:
    # `.cm-content` is transiently absent while the editor mounts; fall back to
    # "" so callers polling on text retry instead of throwing.
    return page.evaluate("() => document.querySelector('.cm-content')?.innerText ?? ''")


def _wait_text(page: Page, needle: str, timeout: float = 15_000) -> None:
    page.wait_for_function(
        "n => (document.querySelector('.cm-content')?.innerText ?? '').includes(n)",
        arg=needle,
        timeout=timeout,
    )


def _style_of_text(page: Page, needle: str) -> dict | None:
    """Computed style of the deepest element whose text contains `needle`.
    Walks ALL elements (not just spans — table cells render real <strong>/
    <del> nodes) in document order, keeping the last match: parents precede
    children, so the survivor is the innermost element of the last
    occurrence — the one whose computed style the user actually sees."""
    return page.evaluate(_STYLE_JS, needle)


def test_inline_emphasis_and_marks(page: Page):
    _open(
        page,
        "inline",
        "plain sentence\n\n"
        "**boldword** and *italword* and ***bolditalword*** and ~~struckword~~\n\n"
        "`codeword` and ==markedword== and H~2~O and X^2^ and last_charged_at\n\n"
        r"escaped \*not-em\* stays literal",
    )
    _wait_text(page, "boldword")
    text = _visible_text(page)

    # live preview hides the markup characters
    for marker in ("**", "~~", "==", "`"):
        assert marker not in text, f"{marker!r} still visible:\n{text}"

    assert int(_style_of_text(page, "boldword")["fontWeight"]) >= 600
    assert _style_of_text(page, "italword")["fontStyle"] == "italic"
    boldital = _style_of_text(page, "bolditalword")
    assert int(boldital["fontWeight"]) >= 600 and boldital["fontStyle"] == "italic"
    assert "line-through" in _style_of_text(page, "struckword")["textDecoration"]

    # extended inline: highlight / sub / sup carry their stable classes
    assert page.locator(".cm-md-mark").count()
    assert _style_of_text(page, "2")  # smoke: spans exist at all
    assert page.locator(".cm-md-sub").count()
    assert page.locator(".cm-md-sup").count()

    # intra-word underscores stay literal (GFM rule)
    assert "last_charged_at" in text
    # escapes render the punctuation, not the backslash
    assert "*not-em*" in text and r"\*" not in text


def test_headings_render_larger_with_marks_hidden(page: Page):
    _open(
        page,
        "headings",
        "# Alpha Heading\n\nbody paragraph\n\nSetext Heading\n===\n",
    )
    _wait_text(page, "Alpha Heading")
    text = _visible_text(page)
    assert "# Alpha" not in text, "ATX marker still visible"
    body_size = _style_of_text(page, "body paragraph")["fontSize"]
    assert _style_of_text(page, "Alpha Heading")["fontSize"] > body_size
    assert _style_of_text(page, "Setext Heading")["fontSize"] > body_size


def test_blocks_lists_quote_hr_and_code(page: Page):
    _open(
        page,
        "blocks",
        "> quoted wisdom\n\n"
        "- first item\n- second item\n  - nested item\n\n"
        "1. ordered one\n2. ordered two\n\n"
        "---\n\n"
        "```python\ndef fenced_fn():\n    return 42\n```\n",
    )
    _wait_text(page, "quoted wisdom")
    text = _visible_text(page)
    for expected in ("quoted wisdom", "first item", "nested item", "ordered one", "fenced_fn"):
        assert expected in text
    # HR line gets its stable class
    assert page.locator(".cm-md-hr").count()
    # syntax highlighting: the `def` keyword is colored differently from
    # plain body text (catppuccin token style applied)
    poll_until(
        lambda: (
            _style_of_text(page, "def")
            and _style_of_text(page, "def")["color"]
            != _style_of_text(page, "quoted wisdom")["color"]
        )
    )


def test_task_lists_render_checkboxes(page: Page):
    _open(page, "tasks", "- [x] done thing\n- [ ] pending thing\n")
    expect(page.locator("input[type=checkbox]")).to_have_count(2)
    assert page.locator("input[type=checkbox]:checked").count() == 1, (
        "exactly the [x] item should be checked"
    )


def test_links_autolinks_and_reference_links(page: Page):
    # Demo lockdown: only in-vault navigation is clickable. External links
    # (inline + reference) render inert; autolinks stay as plain text.
    _open(
        page,
        "links",
        '[titled link](guides/intro "hover text")\n\n'  # internal → clickable
        "[external site](https://example.com)\n\n"  # external → inert
        "<https://autolink.example.com>\n\n"  # autolink → plain text
        "[ref style][lbl]\n\n"
        "[lbl]: https://ref.example.com\n",  # external reference → inert
    )
    _wait_text(page, "titled link")
    text = _visible_text(page)
    # inline URLs are hidden; the labels show
    assert "(https://example.com" not in text
    assert "titled link" in text and "external site" in text and "ref style" in text

    # internal link is clickable: a real .cm-md-link with data-href + title
    clickable = page.locator(".cm-md-link")
    hrefs = {clickable.nth(i).get_attribute("data-href") for i in range(clickable.count())}
    assert "guides/intro" in hrefs
    titled = page.locator('.cm-md-link[data-href="guides/intro"]')
    assert titled.get_attribute("title") == "hover text"

    # external links (inline + reference) are INERT — rendered as
    # .cm-md-link-external carrying no data-href, so nothing is clickable and no
    # external URL ever becomes a live link.
    ext = page.locator(".cm-md-link-external")
    assert ext.count() >= 2
    for i in range(ext.count()):
        assert ext.nth(i).get_attribute("data-href") is None
    assert "https://example.com" not in hrefs
    assert "https://ref.example.com" not in hrefs

    # autolink text stays visible (as plain text, not a decorated link)
    assert "https://autolink.example.com" in text


def test_tables_render_as_grid_except_cursor_row(page: Page):
    _open(
        page,
        "table",
        "| Name | Value |\n| --- | --- |\n| **bold cell** | `code cell` |\n",
    )
    expect(page.locator(".cm-md-table-row").first).to_be_visible()
    cells = page.locator(".cm-md-table-cell").all_inner_texts()
    assert "Name" in cells and "bold cell" in cells and "code cell" in cells
    # separator row collapses to the stripe widget
    assert page.locator(".cm-md-table-separator").count()
    # in-cell formatting is applied, marks hidden
    assert int(_style_of_text(page, "bold cell")["fontWeight"]) >= 600
    assert "**" not in _visible_text(page)


def test_table_rows_stay_contiguous_through_row_navigation(page: Page):
    """Guard: moving the cursor up/down through a tall table's rows must keep
    the rendered rows abutting (no gaps, no leftover visible widgetBuffer).

    Background: the row-gap collapse used to rely on a `:has()` selector whose
    invalidation goes stale on real Safari as rows toggle widget<->raw during
    navigation, leaving CodeMirror's ~1em widgetBuffer visible so rows drift
    apart. The fix collapses the buffer via a class applied straight to the
    `.cm-line` (see `.cm-md-table-line` in style.css), removing the `:has()`
    dependency entirely. NOTE: Playwright's headless WebKit does NOT reproduce
    the intermittent Safari invalidation bug (it passed even with the old
    `:has()` CSS), so this is a general contiguity guard, not the Safari repro —
    that must be confirmed in a real Safari build."""
    # Rich cells (inline `code` / **bold**) like the demo shortcut table, made
    # tall by repetition — both raise the odds of the stale-buffer gap.
    unit = [
        "| `Cmd/Ctrl-K` | Quick switcher — go to or create a note |",
        "| `Cmd/Ctrl-Shift-K` | Rename the current note |",
        "| `Cmd/Ctrl-Backspace` | Delete a note |",
        "| `Cmd/Ctrl-E` | Emoji picker — inserts a `:shortcode:` |",
        "| `Cmd/Ctrl-Alt-O` | Editor options (vim mode, line numbers) |",
        "| `Cmd/Ctrl-U` | Upload — **disabled in this demo** |",
    ]
    data = unit * 6  # 36 data rows
    n = len(data)
    body = "| Shortcut | What it does |\n| --- | --- |\n" + "\n".join(data) + "\n\ntail line\n"
    _open(page, "table-nav", body)
    _wait_text(page, "tail line")

    def contiguity() -> dict:
        """maxGap between consecutive rendered rows + count of visible
        table-line widgetBuffers, for the CURRENT DOM state."""
        return page.evaluate(
            """
            () => {
              const rows = [...document.querySelectorAll(
                '.cm-md-table-row, .cm-md-table-separator')]
              const rects = rows.map(r => r.getBoundingClientRect())
              let maxGap = 0
              for (let i = 1; i < rects.length; i++) {
                maxGap = Math.max(maxGap, rects[i].top - rects[i - 1].bottom)
              }
              const visibleBuffers = [...document.querySelectorAll(
                '.cm-md-table-line > .cm-widgetBuffer')].filter(b => b.offsetHeight > 0).length
              return { count: rows.length, maxGap, visibleBuffers }
            }
            """
        )

    click_editor(page)
    for _ in range(n + 8):
        page.keyboard.press("ArrowUp")  # reach the top
    # Step through the table one row at a time (down then up, a few passes). At
    # every position track visible table-line widgetBuffers — the direct bug
    # symptom, and safe to sample mid-navigation because the raw cursor row
    # carries no `.cm-md-table-line` class (so it's never miscounted; the gap
    # metric, by contrast, would falsely see the raw row's own height).
    max_visible_buffers = 0
    for _ in range(3):
        for direction in ("ArrowDown", "ArrowUp"):
            for _ in range(n + 8):
                page.keyboard.press(direction)
                max_visible_buffers = max(max_visible_buffers, contiguity()["visibleBuffers"])
    # Park below the table so every row renders as a widget — the clean state
    # where a row-to-row gap unambiguously means a leftover buffer.
    for _ in range(n + 8):
        page.keyboard.press("ArrowDown")
    final = contiguity()
    assert final["count"] == n + 2, final  # header + separator + n data rows
    assert final["maxGap"] < 4, final
    assert final["visibleBuffers"] == 0, final
    assert max_visible_buffers == 0, {"max_visible_buffers": max_visible_buffers}


def test_emoji_shortcodes_render_glyphs(page: Page):
    _open(page, "emoji", "shipping :t-rex: and :+1: today\n")
    expect(page.locator(".cm-md-emoji")).to_have_count(2)
    glyphs = page.locator(".cm-md-emoji").all_inner_texts()
    assert "🦖" in glyphs and "👍" in glyphs
    assert ":t-rex:" not in _visible_text(page)
    # the FILE keeps the literal shortcodes — glyphs are render-time only
    raw = read_vault_file(ROOT_VAULT, "features/emoji.md")
    assert raw is not None and ":t-rex:" in raw and ":+1:" in raw


def test_wikilinks_render_and_navigate(page: Page):
    seed_vault_file(ROOT_VAULT, "features/target.md", b"wikilink landing pad\n")
    _open(page, "wiki", "go to [[features/target]] or [[features/target|the alias]]\n")
    expect(page.locator(".cm-md-wikilink")).to_have_count(2)
    text = _visible_text(page)
    assert "[[" not in text, "wikilink brackets still visible"
    assert "the alias" in text
    assert "|" not in text.split("or")[1], "alias form must hide the target"
    # clicking navigates via the SPA router to the target note
    page.locator(".cm-md-wikilink").first.click()
    expect(page).to_have_url(re.compile(r"/features/target$"))
    expect(page.locator(".cm-content")).to_contain_text("wikilink landing pad")


def test_direct_image_url_renders_pixels(page: Page):
    """A typed/bookmarked image URL must render the image. Over plain HTTP
    (this suite's network — browsers withhold Fetch Metadata off https/
    localhost) the backend serves raw bytes and the browser shows its native
    image document; either way the user sees pixels — the SPA-viewer path
    itself is pinned by test_asset_refresh.py via in-app navigation."""
    from conftest import TINY_PNG

    seed_vault_file(ROOT_VAULT, "viewer/solo.png", TINY_PNG)
    page.goto(f"{ROOT_URL}/viewer/solo.png")
    page.wait_for_function(
        "() => [...document.querySelectorAll('img')]"
        ".some(i => i.src && i.complete && i.naturalWidth > 0)"
    )
