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
    CRDT_LOAD_TIMEOUT,
    ROOT_URL,
    ROOT_VAULT,
    click_editor,
    expect_editor_contains,
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
    _open(
        page,
        "links",
        '[titled link](https://example.com "hover text")\n\n'
        "<https://autolink.example.com>\n\n"
        "[ref style][lbl]\n\n"
        "[lbl]: https://ref.example.com\n",
    )
    _wait_text(page, "titled link")
    text = _visible_text(page)
    # inline link URL is hidden; the label is decorated and titled
    assert "(https://example.com" not in text
    link_els = page.locator(".cm-md-link")
    links = {
        link_els.nth(i).get_attribute("data-href"): link_els.nth(i)
        for i in range(link_els.count())
    }
    assert "https://example.com" in links
    assert links["https://example.com"].get_attribute("title") == "hover text"
    # reference form resolves through its label definition
    assert "https://ref.example.com" in links
    # autolink text stays visible (clickable URL)
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
    expect_editor_contains(page, "wikilink landing pad")


# Section names are unique per level so each anchor + revealed heading locates
# exactly one element; the level number is baked into the name for readability.
_SECTION_LEVELS = [
    (1, "Alpha One"),
    (2, "Bravo Two"),
    (3, "Charlie Three"),
    (4, "Delta Four"),
    (5, "Echo Five"),
    (6, "Foxtrot Six"),
]


def test_wiki_section_links_scroll_within_note(page: Page):
    """`[[#Heading]]` jumps to that heading in the CURRENT note, for all six
    ATX levels. Tall filler forces a real scroll; clicking the anchor places
    the cursor on the target heading (revealing its raw `#` markers, so the
    level is observable) and scrolls it into the viewport."""
    filler = "\n\n".join(f"filler line {i}" for i in range(40))
    anchors = "\n\n".join(f"[[#{name}]]" for _, name in _SECTION_LEVELS)
    sections = "\n\n".join(
        f"{'#' * lvl} {name}\n\n{filler}" for lvl, name in _SECTION_LEVELS
    )
    _open(page, "sections", f"{anchors}\n\n{filler}\n\n{sections}\n")
    # Gate on the anchors rendering — proves the note synced + parsed. All six
    # anchors sit at the top of the doc, so they're rendered at the initial
    # scroll position.
    expect(page.locator(".cm-md-wikilink")).to_have_count(
        len(_SECTION_LEVELS), timeout=CRDT_LOAD_TIMEOUT
    )

    scroller = page.locator(".cm-scroller")
    for lvl, name in _SECTION_LEVELS:
        # CodeMirror culls off-screen lines, so a prior jump to a bottom heading
        # removes the top anchors from the DOM. Reset to the top before each
        # click so the anchor is present and clickable.
        scroller.evaluate("el => { el.scrollTop = 0 }")
        # Anchor label is "#Name" (no space); the revealed heading is
        # "#...# Name" (space after the hashes) — distinct substrings, so the
        # class-scoped anchor locator and the heading text locator never cross.
        page.locator(".cm-md-wikilink", has_text=f"#{name}").click()
        revealed = page.get_by_text(f"{'#' * lvl} {name}").first
        expect(revealed).to_be_in_viewport(timeout=CRDT_LOAD_TIMEOUT)


def test_wiki_section_link_setext_within_note(page: Page):
    """Section jump also resolves a Setext heading (`Heading\\n===`)."""
    filler = "\n\n".join(f"pad {i}" for i in range(40))
    _open(page, "sections-setext", f"[[#Setext Target]]\n\n{filler}\n\nSetext Target\n===\n")
    expect(page.locator(".cm-md-wikilink")).to_have_count(1, timeout=CRDT_LOAD_TIMEOUT)
    page.locator(".cm-md-wikilink").first.click()
    # Target the styled Setext heading LINE (class cm-md-h1), not bare text —
    # the anchor "#Setext Target" contains "Setext Target" as a substring.
    expect(page.locator(".cm-md-h1", has_text="Setext Target")).to_be_in_viewport(
        timeout=CRDT_LOAD_TIMEOUT
    )


def test_wiki_section_link_across_notes(page: Page):
    """`[[note#Heading]]` navigates to another note AND scrolls to the heading
    once that note's content loads over CRDT. The aliased form shows its alias
    but still carries the anchor."""
    filler = "\n\n".join(f"far below {i}" for i in range(40))
    seed_vault_file(
        ROOT_VAULT,
        "features/deep.md",
        (f"deep intro line\n\n{filler}\n\n## Deep Section\n\n{filler}\n").encode(),
    )
    _open(page, "sections-x", "cross ref [[features/deep#Deep Section|go deep]]\n")
    link = page.locator(".cm-md-wikilink")
    expect(link).to_have_count(1, timeout=CRDT_LOAD_TIMEOUT)
    expect(link).to_have_text("go deep")
    link.click()
    expect(page).to_have_url(re.compile(r"/features/deep$"))
    # The heading is 40 filler lines down, past the top of the note (whose intro
    # line CodeMirror culls once we're scrolled away). The cross-note jump must
    # have loaded the note AND scrolled the heading into view — revealing its
    # markers by placing the cursor there. The 30s headroom covers CRDT load.
    expect(page.get_by_text("## Deep Section").first).to_be_in_viewport(
        timeout=CRDT_LOAD_TIMEOUT
    )


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
