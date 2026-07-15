"""Embedded-image matrix: every supported embed shape must actually decode
in the browser, at a root mount AND under BASE_URL=/wiki.

Markdown `![alt](url)` shapes (resolved against the note `embeds/note.md`,
per the vault-relative resolution rule):
  - sibling            pic.png                  -> embeds/pic.png
  - subdirectory       sub/pic2.png             -> embeds/sub/pic2.png
  - parent traversal   ../shared/pic.png        -> shared/pic.png
  - root-absolute      /abs/pic3.png            -> abs/pic3.png
  - encoded spaces     ../my%20pics/my%20pic.png -> "my pics/my pic.png"
  - empty alt, standalone and inline mid-sentence

Wikilink `![[target]]` embeds fetch ONE `/api/embed` URL; the SERVER
resolves adjacent-to-note first, vault root second. The shadow case seeds
the same target at both locations with different dimensions and requires
the adjacent one to render.
"""

from pathlib import Path
from urllib.parse import quote

import pytest
from playwright.sync_api import Page, expect

from conftest import (
    ROOT_URL,
    ROOT_VAULT,
    TINY_PNG,
    WIKI_HOST,
    WIKI_PREFIX,
    WIKI_URL,
    WIKI_VAULT,
    make_png,
    seed_vault_file,
)

NOTE = b"""# embeds

![sibling](pic.png)

![subdir](sub/pic2.png)

![traversal](../shared/pic.png)

![absolute](/abs/pic3.png)

![spaces](../my%20pics/my%20pic.png)

![](empty-alt.png)

before ![](inline.png) after, in running text

![[attachments-e2e/obsidian.png]]

![[attachments-e2e/aliased.png|the alias]]

![[near-note/relative.png]]

![[shadow/adj.png]]
"""

# vault file -> the path the browser must end up requesting (pre-prefix)
EXPECTED = {
    "embeds/pic.png": "/embeds/pic.png",
    "embeds/sub/pic2.png": "/embeds/sub/pic2.png",
    "shared/pic.png": "/shared/pic.png",
    "abs/pic3.png": "/abs/pic3.png",
    "my pics/my pic.png": "/my%20pics/my%20pic.png",
    # empty alt (`![]`) — used to be silently skipped by the renderer
    "embeds/empty-alt.png": "/embeds/empty-alt.png",
    # inline mid-sentence, also empty alt
    "embeds/inline.png": "/embeds/inline.png",
}

# wikilink-embed target -> required decoded naturalWidth (None = any > 0).
# All are 1x1 except the shadow proof: the adjacent copy is 1x1 while its
# root twin is 2x2, so width==1 proves adjacent overshadowed root.
WIKILINK_EMBEDS = {
    "attachments-e2e/obsidian.png": None,  # root-only -> server fallback
    "attachments-e2e/aliased.png": None,  # root-only, alias form
    "near-note/relative.png": None,  # adjacent-only (embeds/near-note/)
    "shadow/adj.png": 1,  # exists at BOTH; adjacent must win
}


def _seed(vault: Path) -> None:
    for vault_path in EXPECTED:
        seed_vault_file(vault, vault_path, TINY_PNG)
    seed_vault_file(vault, "attachments-e2e/obsidian.png", TINY_PNG)
    seed_vault_file(vault, "attachments-e2e/aliased.png", TINY_PNG)
    seed_vault_file(vault, "embeds/near-note/relative.png", TINY_PNG)
    seed_vault_file(vault, "embeds/shadow/adj.png", TINY_PNG)  # adjacent: 1x1
    seed_vault_file(vault, "shadow/adj.png", make_png(2, 2))  # root twin: 2x2
    seed_vault_file(vault, "embeds/note.md", NOTE)


def _img_states(page: Page) -> list[dict]:
    return page.eval_on_selector_all(
        "img",
        """
        els => els.filter(i => i.getAttribute('src')).map(i => ({
          src: i.getAttribute('src'),
          width: i.complete ? i.naturalWidth : 0,
        }))
        """,
    )


@pytest.mark.parametrize("mount", ["root", "subpath"])
def test_all_embed_shapes_decode(page: Page, mount):
    if mount == "root":
        base, prefix, vault = ROOT_URL, "", ROOT_VAULT
    else:
        base, prefix, vault = WIKI_URL, WIKI_PREFIX, WIKI_VAULT
    _seed(vault)

    total = len(EXPECTED) + len(WIKILINK_EMBEDS)
    page.goto(f"{base}/embeds/note")
    expect(page.locator(".cm-content")).to_be_visible()
    page.wait_for_function(
        "total => [...document.querySelectorAll('img')]"
        ".filter(i => i.complete && i.naturalWidth > 0).length >= total",
        arg=total,
        timeout=25_000,
    )

    states = _img_states(page)
    for expected in EXPECTED.values():
        want = prefix + expected
        matching = [s for s in states if s["src"].endswith(want) and s["width"] > 0]
        assert matching, f"no decoded <img> for {want}; got {states}"

    for target, want_width in WIKILINK_EMBEDS.items():
        marker = "target=" + quote(target, safe="")
        matching = [s for s in states if marker in s["src"] and s["width"] > 0]
        assert matching, f"no decoded /api/embed <img> for {target}; got {states}"
        assert f"{prefix}/api/embed?" in matching[0]["src"], matching[0]
        if want_width is not None:
            assert matching[0]["width"] == want_width, (
                f"{target}: expected the ADJACENT copy (width {want_width}), "
                f"got width {matching[0]['width']} — root overshadowed adjacent"
            )

    # Nothing may escape the prefix under the sub-path mount. src attributes
    # are relative (`/wiki/...`); absolute forms must carry host + prefix.
    if prefix:
        escaped = [
            s["src"]
            for s in states
            if not (
                s["src"].startswith(f"{prefix}/")
                or f"//{WIKI_HOST}{prefix}" in s["src"]
            )
        ]
        assert not escaped, f"embeds escaped the prefix: {escaped}"
