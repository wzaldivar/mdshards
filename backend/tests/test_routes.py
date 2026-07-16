import pytest


def test_config_exposes_home_path_default_empty(client) -> None:
    c, _ = client
    body = c.get("/_mdshards/api/config").json()
    assert body["homePath"] == ""
    assert "gracePeriodSeconds" in body


def test_config_exposes_home_path_when_base_url_set(client, monkeypatch) -> None:
    monkeypatch.setenv("BASE_URL", "/wiki")
    from app import config

    config.get_settings.cache_clear()
    c, _ = client
    body = c.get("/_mdshards/api/config").json()
    assert body["homePath"] == "/wiki"


def test_index_url_redirects_to_root(client) -> None:
    c, _ = client
    r = c.get("/index", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/"


def test_root_serves_spa_shell_and_materializes_index(client) -> None:
    c, vault = client
    r = c.get("/")
    assert r.status_code == 200
    assert 'id="app"' in r.text
    assert (vault / "index.md").exists()


def test_existing_md_serves_spa_shell(client) -> None:
    c, vault = client
    (vault / "notes").mkdir()
    (vault / "notes" / "today.md").write_text("hi")
    r = c.get("/notes/today")
    assert r.status_code == 200
    assert 'id="app"' in r.text


def test_missing_path_doc_nav_serves_spa_shell(client) -> None:
    """Missing URLs no longer redirect to `/` — a top-level browser nav (which
    sends Sec-Fetch-Dest=document) gets the SPA shell so the React NotFound
    view can render with a "Go home" button."""
    c, _ = client
    r = c.get(
        "/no/such/page",
        headers={"sec-fetch-dest": "document"},
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert '<div id="app"></div>' in r.text


# ---- /_mdshards/api/embed — wikilink image-embed resolution ----
#
# ONE request from the browser; the server resolves the `![[target]]`
# against two candidate locations with fixed priority: adjacent to the
# embedding note first, vault root second.


def test_embed_adjacent_overshadows_root(client) -> None:
    c, vault = client
    (vault / "notes" / "attachments").mkdir(parents=True)
    (vault / "attachments").mkdir()
    (vault / "notes" / "attachments" / "pic.png").write_bytes(b"ADJACENT")
    (vault / "attachments" / "pic.png").write_bytes(b"ROOT")
    r = c.get(
        "/_mdshards/api/embed", params={"note": "notes/today", "target": "attachments/pic.png"}
    )
    assert r.status_code == 200
    assert r.content == b"ADJACENT"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-cache"


def test_embed_falls_back_to_vault_root(client) -> None:
    c, vault = client
    (vault / "attachments").mkdir()
    (vault / "attachments" / "pic.png").write_bytes(b"ROOT")
    r = c.get(
        "/_mdshards/api/embed", params={"note": "notes/today", "target": "attachments/pic.png"}
    )
    assert r.status_code == 200
    assert r.content == b"ROOT"


def test_embed_root_note_resolves_from_root(client) -> None:
    c, vault = client
    (vault / "pic.png").write_bytes(b"ROOT")
    r = c.get("/_mdshards/api/embed", params={"note": "index", "target": "pic.png"})
    assert r.status_code == 200
    assert r.content == b"ROOT"


def test_embed_missing_both_locations_404s(client) -> None:
    c, _ = client
    r = c.get("/_mdshards/api/embed", params={"note": "notes/today", "target": "nope.png"})
    assert r.status_code == 404


def test_embed_dotdot_stays_inside_vault(client) -> None:
    """`..` inside a target is fine while the result stays in the vault
    (Obsidian's relative link format writes them); escaping candidates are
    skipped, and a fully-escaping target is refused outright."""
    c, vault = client
    (vault / "shared").mkdir()
    (vault / "shared" / "pic.png").write_bytes(b"SHARED")
    r = c.get("/_mdshards/api/embed", params={"note": "notes/today", "target": "../shared/pic.png"})
    assert r.status_code == 200
    assert r.content == b"SHARED"
    r = c.get("/_mdshards/api/embed", params={"note": "index", "target": "../../etc/passwd"})
    assert r.status_code == 400


def test_embed_refuses_md_targets(client) -> None:
    c, vault = client
    (vault / "secret.md").write_text("note bytes")
    r = c.get("/_mdshards/api/embed", params={"note": "index", "target": "secret.md"})
    assert r.status_code == 400


def test_embed_scriptable_suffix_gets_csp_sandbox(client) -> None:
    c, vault = client
    (vault / "img.svg").write_text("<svg/>")
    r = c.get("/_mdshards/api/embed", params={"note": "index", "target": "img.svg"})
    assert r.status_code == 200
    assert r.headers["content-security-policy"] == "sandbox"


# ---- sub-path containment (BASE_URL shell rewrite) ----
#
# With BASE_URL set the served shell must be fully self-contained under the
# prefix: root-rooted src/href attributes rewritten to live under it, and a
# `mdshards-home-path` meta injected so the bundle prefixes its runtime
# fetches (frontend lib/backend.ts). Serve-time only — dist/ stays unbaked.

_FAKE_INDEX_HTML = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<link rel="icon" type="image/svg+xml" href="/_mdshards/favicon.svg" />'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />'
    '<script type="module" crossorigin src="/_mdshards/assets/index-abc.js"></script>'
    '<link rel="stylesheet" crossorigin href="/_mdshards/assets/index-abc.css">'
    '</head><body><div id="app"></div></body></html>'
)


@pytest.fixture
def subpath_client(vault, tmp_path, monkeypatch):
    """Client with BASE_URL=/notes and a fake prebuilt bundle (static/), to
    exercise the serve-time shell rewrite and the prefixed /assets mount."""
    static = tmp_path / "static"
    (static / "_mdshards" / "assets").mkdir(parents=True)
    (static / "index.html").write_text(_FAKE_INDEX_HTML)
    (static / "_mdshards" / "assets" / "index-abc.js").write_text("console.log(1)")
    (static / "_mdshards" / "favicon.svg").write_text("<svg></svg>")
    monkeypatch.setenv("BASE_URL", "/notes")
    from app import config

    monkeypatch.setattr(config, "_BUNDLED_STATIC", static)
    config.get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(), headers={"sec-fetch-site": "same-origin"}) as c:
        yield c, vault
    config.get_settings.cache_clear()


def test_subpath_shell_prefixes_bundle_refs_and_injects_home_path(subpath_client) -> None:
    c, _ = subpath_client
    r = c.get("/notes/", headers={"sec-fetch-dest": "document"})
    assert r.status_code == 200
    assert 'src="/notes/_mdshards/assets/index-abc.js"' in r.text
    assert 'href="/notes/_mdshards/assets/index-abc.css"' in r.text
    assert 'href="/notes/_mdshards/favicon.svg"' in r.text
    assert '<meta name="mdshards-home-path" content="/notes">' in r.text
    # External URLs are untouched.
    assert 'href="https://fonts.gstatic.com"' in r.text


def test_subpath_assets_served_under_prefix(subpath_client) -> None:
    c, _ = subpath_client
    r = c.get("/notes/_mdshards/assets/index-abc.js")
    assert r.status_code == 200
    assert r.text == "console.log(1)"


def test_subpath_index_redirect_keeps_prefix(subpath_client) -> None:
    c, _ = subpath_client
    r = c.get("/notes/index", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/notes/"


def test_root_mount_shell_is_untouched(client) -> None:
    """Without BASE_URL the shell must be byte-identical to what's on disk —
    no meta, no rewritten refs (the placeholder shell in dev/tests)."""
    c, _ = client
    r = c.get("/", headers={"sec-fetch-dest": "document"})
    assert r.status_code == 200
    assert "mdshards-home-path" not in r.text


def test_missing_path_nav_without_fetch_metadata_serves_shell(bare_client) -> None:
    """Browsers omit ALL Sec-Fetch-* headers off https/localhost, so a
    top-level nav from a plain-HTTP LAN address arrives with no
    Sec-Fetch-Dest. It still advertises text/html in Accept — that must be
    enough to get the SPA shell so the NotFound view renders."""
    c, _ = bare_client
    r = c.get(
        "/no/such/page",
        headers={"accept": "text/html,application/xhtml+xml"},
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert '<div id="app"></div>' in r.text


def test_missing_path_subresource_returns_404(client) -> None:
    """A sub-resource fetch (img/iframe) for a missing path should 404, not
    serve the SPA shell — otherwise broken `<img src>` references would
    render HTML as image bytes."""
    c, _ = client
    r = c.get(
        "/no/such/page.png",
        headers={"sec-fetch-dest": "image"},
        follow_redirects=False,
    )
    assert r.status_code == 404


def test_dotty_md_url_resolves_to_md(client) -> None:
    """`/notes/my.weekly` should serve the SPA when `notes/my.weekly.md` exists,
    even though the URL has a dot in the last segment."""
    c, vault = client
    (vault / "notes").mkdir()
    (vault / "notes" / "my.weekly.md").write_text("hi")
    r = c.get("/notes/my.weekly", follow_redirects=False)
    assert r.status_code == 200
    assert '<div id="app"></div>' in r.text


def test_md_url_with_literal_md_file_serves_shell(client) -> None:
    """A `.md` URL is allowed now. If the canonical doc-id form
    (`<vault>/x.md.md`) doesn't exist but the literal `<vault>/x.md` does —
    which is itself a markdown note with doc-id `x` — the catch-all serves
    the SPA shell (no server 302). The SPA canonicalizes `/x.md` → `/x`
    client-side from `/_mdshards/api/resolve`'s `canonical` field
    (test_resolve_md_url_falls_back_to_canonical covers that contract)."""
    c, vault = client
    (vault / "x.md").write_text("hi")
    r = c.get("/x.md", follow_redirects=False)
    assert r.status_code == 200
    assert '<div id="app"></div>' in r.text


def test_md_url_with_nested_md_md_serves_directly(client) -> None:
    """When BOTH `<vault>/foo.md.md` and `<vault>/foo.md` exist, the URL
    `/foo.md` is canonical for the note at `foo.md.md` (its doc-id is
    `foo.md`). No redirect, SPA shell."""
    c, vault = client
    (vault / "foo.md.md").write_text("doc-id is foo.md")
    (vault / "foo.md").write_text("doc-id is foo")
    r = c.get("/foo.md", follow_redirects=False)
    assert r.status_code == 200
    assert '<div id="app"></div>' in r.text


def test_asset_doc_nav_returns_spa_shell(client) -> None:
    """Browser nav to an asset URL (Sec-Fetch-Dest=document) must land inside
    the SPA so editor shortcuts stay live. The AssetViewer's iframe re-fetches
    with Sec-Fetch-Dest=iframe and gets the real bytes (covered below)."""
    c, vault = client
    (vault / "notes").mkdir()
    (vault / "notes" / "diagram.png").write_bytes(b"\x89PNG")
    r = c.get(
        "/notes/diagram.png",
        headers={"sec-fetch-dest": "document"},
    )
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert '<div id="app"></div>' in r.text


def test_asset_iframe_fetch_returns_bytes(client) -> None:
    """A sub-resource fetch (iframe / image / video) for the same URL must
    still get the file bytes — the SPA-shell return only applies to doc nav."""
    c, vault = client
    (vault / "notes").mkdir()
    (vault / "notes" / "diagram.png").write_bytes(b"\x89PNG")
    r = c.get(
        "/notes/diagram.png",
        headers={"sec-fetch-dest": "iframe"},
    )
    assert r.status_code == 200
    assert r.content.startswith(b"\x89PNG")


def test_asset_response_carries_sandbox_and_nosniff_headers(client) -> None:
    """Defense-in-depth for the iframe-XSS path: even if a legacy browser
    skips Sec-Fetch-Dest and pulls a vault `.html` as a top-level navigation,
    `CSP: sandbox` neutralizes scripts and `nosniff` prevents content-type
    sniffing from upgrading an asset to text/html."""
    c, vault = client
    (vault / "page.html").write_text("<script>alert(1)</script>")
    r = c.get("/page.html", headers={"sec-fetch-dest": "iframe"})
    assert r.status_code == 200
    assert r.headers["content-security-policy"] == "sandbox"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_only_scriptable_assets_are_sandboxed(client) -> None:
    """`CSP: sandbox` is applied ONLY to script-capable types — a blanket
    sandbox blocks the PDF viewer plugin and swallows download fallbacks
    (blank page instead of a save). Non-scriptable types get browser-default
    handling; nosniff/no-cache apply to everything."""
    c, vault = client
    (vault / "doc.pdf").write_bytes(b"%PDF-1.4 fake")
    (vault / "notes.txt").write_text("plain text")
    (vault / "data.tar.gz").write_bytes(b"\x1f\x8b")
    (vault / "img.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    for name in ("doc.pdf", "notes.txt", "data.tar.gz"):
        r = c.get(f"/{name}", headers={"sec-fetch-dest": "iframe"})
        assert r.status_code == 200
        assert "content-security-policy" not in r.headers, name
        assert r.headers["x-content-type-options"] == "nosniff", name
        assert r.headers["cache-control"] == "no-cache", name
    r = c.get("/img.svg", headers={"sec-fetch-dest": "iframe"})
    assert r.headers["content-security-policy"] == "sandbox"


def test_asset_response_is_not_cached(client) -> None:
    """Vault assets are mutable (delete / overwrite / external rewrite), so the
    response must force revalidation — otherwise the browser keeps serving a
    removed or stale asset from its heuristic cache."""
    c, vault = client
    (vault / "pic.png").write_bytes(b"\x89PNG")
    r = c.get("/pic.png", headers={"sec-fetch-dest": "image"})
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"


def test_existing_asset_serves(client) -> None:
    c, vault = client
    (vault / "a").mkdir()
    (vault / "a" / "b.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    r = c.get("/a/b.png")
    assert r.status_code == 200
    assert r.content.startswith(b"\x89PNG")


def test_missing_asset_subresource_returns_404(client) -> None:
    """A sub-resource fetch (no Sec-Fetch-Dest=document) for a missing path
    returns 404 — same as before the catch-all refactor."""
    c, _ = client
    r = c.get("/missing/file.png")
    assert r.status_code == 404


def test_image_subresource_outside_vault_returns_404(client) -> None:
    """The end-to-end "no out-of-vault retrieval" guarantee. A markdown
    ref like `![](../../etc/passwd)` is normalized by the browser's URL
    constructor to `/etc/passwd` (../ caps at origin root) — which the
    backend must still refuse to serve from outside the vault. Since the
    vault has no `etc/passwd`, the catch-all returns 404 for the image
    sub-resource fetch. Defense in depth: even if a writer somehow tried
    to point at a sibling-of-vault file, `assert_inside` would reject it
    first."""
    c, _ = client
    r = c.get("/etc/passwd", headers={"sec-fetch-dest": "image"})
    assert r.status_code == 404


def test_traversal_in_url_path_rejected(client) -> None:
    """A literal `..` segment in a sub-resource request URL is rejected
    with 400 — the browser would normally normalize this away, but a
    hand-crafted client mustn't get a back-door into the parent of the
    vault root."""
    c, _ = client
    r = c.get("/notes/..%2F..%2Fetc/passwd", headers={"sec-fetch-dest": "image"})
    # Either 400 (path validation refused) or 404 (no such asset). Both
    # are acceptable — neither serves a file from outside the vault.
    assert r.status_code in (400, 404)


def test_spaces_in_url_ok(client) -> None:
    c, vault = client
    (vault / "has space.md").write_text("hi")
    # A spaced md URL is served the SPA shell like any other note (no 400).
    r = c.get("/has%20space")
    assert r.status_code == 200


def test_create_file(client) -> None:
    c, vault = client
    r = c.post("/_mdshards/api/files", json={"path": "notes/hello"})
    assert r.status_code == 201
    assert (vault / "notes" / "hello.md").exists()


def test_create_file_with_content(client) -> None:
    c, vault = client
    r = c.post("/_mdshards/api/files", json={"path": "notes/imported", "content": "# Hi\n"})
    assert r.status_code == 201
    assert (vault / "notes" / "imported.md").read_text() == "# Hi\n"


def test_create_file_conflict(client) -> None:
    c, vault = client
    (vault / "x.md").write_text("")
    r = c.post("/_mdshards/api/files", json={"path": "x"})
    assert r.status_code == 409


def test_create_file_allows_spaces(client) -> None:
    c, vault = client
    r = c.post("/_mdshards/api/files", json={"path": "has space"})
    assert r.status_code == 201
    assert (vault / "has space.md").exists()


def test_create_file_rejects_traversal(client) -> None:
    c, _ = client
    r = c.post("/_mdshards/api/files", json={"path": "../escape"})
    assert r.status_code == 400


def test_create_under_attachments_forbidden(client) -> None:
    """DEMO: the attachments/ directory is seeded-only — creating a note under
    it is refused (403), so users can't pollute the asset namespace."""
    c, vault = client
    r = c.post("/_mdshards/api/files", json={"path": "attachments/foo"})
    assert r.status_code == 403
    assert not (vault / "attachments" / "foo.md").exists()


def test_move_into_attachments_forbidden(client) -> None:
    c, vault = client
    (vault / "note.md").write_text("keep")
    r = c.post("/_mdshards/api/files/move", json={"src": "note", "dst": "attachments/note"})
    assert r.status_code == 403
    assert (vault / "note.md").exists()


def test_root_note_named_attachments_allowed(client) -> None:
    """A root note `attachments.md` is NOT inside the attachments/ directory, so
    it stays creatable — only paths UNDER attachments/ are reserved."""
    c, vault = client
    r = c.post("/_mdshards/api/files", json={"path": "attachments"})
    assert r.status_code == 201
    assert (vault / "attachments.md").exists()


def test_attachments_asset_still_serves(client) -> None:
    """Reads from attachments/ stay open — the seeded demo assets render."""
    c, vault = client
    (vault / "attachments").mkdir()
    (vault / "attachments" / "pic.png").write_bytes(b"\x89PNG")
    r = c.get("/attachments/pic.png", headers={"sec-fetch-dest": "image"})
    assert r.status_code == 200


def test_delete_file_and_prune(client) -> None:
    c, vault = client
    (vault / "a").mkdir()
    (vault / "a" / "b.md").write_text("")
    r = c.delete("/_mdshards/api/files/a/b")
    assert r.status_code == 200
    assert not (vault / "a" / "b.md").exists()
    assert not (vault / "a").exists()


def test_move_renames_file_and_prunes_source_dirs(client) -> None:
    c, vault = client
    (vault / "old" / "nested").mkdir(parents=True)
    (vault / "old" / "nested" / "note.md").write_text("body")
    r = c.post(
        "/_mdshards/api/files/move", json={"src": "old/nested/note", "dst": "new/place/note"}
    )
    assert r.status_code == 200
    assert (vault / "new" / "place" / "note.md").read_text() == "body"
    assert not (vault / "old").exists()


def test_move_rejects_existing_destination(client) -> None:
    c, vault = client
    (vault / "a.md").write_text("")
    (vault / "b.md").write_text("")
    r = c.post("/_mdshards/api/files/move", json={"src": "a", "dst": "b"})
    assert r.status_code == 409


def test_move_endpoints_have_no_overwrite_escape(client) -> None:
    """INVARIANT: /_mdshards/api/files/move must 409 on an existing destination
    even if a caller smuggles an `overwrite` field into the body. The overwrite
    flag exists only on POST /_mdshards/api/files (md create); the move endpoint
    never honors it. (The demo build has no asset mutation endpoints at all.)"""
    c, vault = client
    (vault / "a.md").write_text("keep a")
    (vault / "b.md").write_text("keep b")
    r = c.post("/_mdshards/api/files/move", json={"src": "a", "dst": "b", "overwrite": True})
    assert r.status_code == 409
    assert (vault / "b.md").read_text() == "keep b"


def test_move_rejects_index(client) -> None:
    c, vault = client
    (vault / "x.md").write_text("")
    c.get("/")  # materialize index.md
    r = c.post("/_mdshards/api/files/move", json={"src": "index", "dst": "x_renamed"})
    assert r.status_code == 403
    r = c.post("/_mdshards/api/files/move", json={"src": "x", "dst": "index"})
    assert r.status_code == 403


def test_move_allows_spaces(client) -> None:
    c, vault = client
    (vault / "a.md").write_text("")
    r = c.post("/_mdshards/api/files/move", json={"src": "a", "dst": "with space"})
    assert r.status_code == 200
    assert (vault / "with space.md").exists()


def test_delete_index_refused(client) -> None:
    c, _ = client
    c.get("/")
    r = c.delete("/_mdshards/api/files/index")
    assert r.status_code == 403


def test_delete_missing_404(client) -> None:
    c, _ = client
    r = c.delete("/_mdshards/api/files/never/existed")
    assert r.status_code == 404


def test_tree_endpoint(client) -> None:
    c, vault = client
    (vault / "a").mkdir()
    (vault / "a" / "b.md").write_text("")
    (vault / "c.md").write_text("")
    r = c.get("/_mdshards/api/tree")
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "dir"
    names = {child["name"] for child in body["children"]}
    assert "a" in names and "c.md" in names


def test_md_create_collision_requires_explicit_overwrite(client) -> None:
    """An existing note 409s unless `overwrite` is set — the md-upload flow's
    accept-or-rename prompt sets it; the quick-switcher never does, so
    Shift-Enter can never replace an existing file."""
    c, vault = client
    (vault / "note.md").write_text("original")
    r = c.post("/_mdshards/api/files", json={"path": "note", "content": "replacement"})
    assert r.status_code == 409
    assert (vault / "note.md").read_text() == "original"

    r = c.post(
        "/_mdshards/api/files", json={"path": "note", "content": "replacement", "overwrite": True}
    )
    assert r.status_code == 201
    assert (vault / "note.md").read_text() == "replacement"


def test_resolve_root_is_md(client) -> None:
    c, _ = client
    r = c.get("/_mdshards/api/resolve")
    assert r.status_code == 200
    assert r.json() == {"type": "md", "canonical": ""}


def test_resolve_index_is_md(client) -> None:
    c, _ = client
    r = c.get("/_mdshards/api/resolve/index")
    assert r.status_code == 200
    assert r.json() == {"type": "md", "canonical": ""}


def test_resolve_existing_md(client) -> None:
    c, vault = client
    (vault / "notes").mkdir()
    (vault / "notes" / "today.md").write_text("hi")
    r = c.get("/_mdshards/api/resolve/notes/today")
    assert r.json() == {"type": "md", "canonical": "notes/today"}


def test_resolve_dotty_md(client) -> None:
    """Disk file `notes/my.weekly.md` → URL `/notes/my.weekly` resolves as md."""
    c, vault = client
    (vault / "notes").mkdir()
    (vault / "notes" / "my.weekly.md").write_text("hi")
    r = c.get("/_mdshards/api/resolve/notes/my.weekly")
    assert r.json() == {"type": "md", "canonical": "notes/my.weekly"}


def test_resolve_existing_asset(client) -> None:
    c, vault = client
    (vault / "notes").mkdir()
    (vault / "notes" / "diagram.png").write_bytes(b"\x89PNG")
    r = c.get("/_mdshards/api/resolve/notes/diagram.png")
    assert r.json() == {"type": "asset", "canonical": "notes/diagram.png"}


def test_resolve_md_wins_over_existing_asset(client) -> None:
    """`foo.jpg.md` exists alongside `foo.jpg` — md wins per the rule."""
    c, vault = client
    (vault / "foo.jpg.md").write_text("the note about the picture")
    (vault / "foo.jpg").write_bytes(b"\xff\xd8\xff")
    r = c.get("/_mdshards/api/resolve/foo.jpg")
    assert r.json() == {"type": "md", "canonical": "foo.jpg"}


def test_resolve_md_url_falls_back_to_canonical(client) -> None:
    """URL `foo.md` with no `<vault>/foo.md.md` but with `<vault>/foo.md`
    on disk: the literal file is itself an md note with doc-id `foo`.
    Canonical URL is `/foo`."""
    c, vault = client
    (vault / "foo.md").write_text("hi")
    r = c.get("/_mdshards/api/resolve/foo.md")
    assert r.json() == {"type": "md", "canonical": "foo"}


def test_resolve_md_url_with_nested_md_md(client) -> None:
    """When `<vault>/foo.md.md` exists, `/foo.md` is canonical (doc-id is
    `foo.md`, no `.md` to strip from the URL)."""
    c, vault = client
    (vault / "foo.md.md").write_text("doc-id is foo.md")
    r = c.get("/_mdshards/api/resolve/foo.md")
    assert r.json() == {"type": "md", "canonical": "foo.md"}


def test_resolve_missing(client) -> None:
    c, _ = client
    r = c.get("/_mdshards/api/resolve/no/such/thing")
    assert r.json() == {"type": "missing", "canonical": "no/such/thing"}


def test_resolve_missing_dotty(client) -> None:
    c, _ = client
    r = c.get("/_mdshards/api/resolve/no/such/thing.png")
    assert r.json() == {"type": "missing", "canonical": "no/such/thing.png"}


def test_resolve_missing_md_url_canonicalizes(client) -> None:
    """A `.md` URL with no on-disk match falls through to the canonical
    extensionless form (which is also missing). The frontend will redirect
    `/foo.md` → `/foo` and then show NotFound at the canonical address."""
    c, _ = client
    r = c.get("/_mdshards/api/resolve/no.md")
    assert r.json() == {"type": "missing", "canonical": "no"}


def test_resolve_allows_spaces(client) -> None:
    c, vault = client
    (vault / "with space.md").write_text("")
    r = c.get("/_mdshards/api/resolve/with space")
    assert r.status_code == 200
    assert r.json() == {"type": "md", "canonical": "with space"}


def test_resolve_root_regenerates_missing_index(client) -> None:
    """/_mdshards/api/resolve is the one call every navigation to `/` makes regardless
    of who served the SPA shell (dev server, preview, nginx, static host) —
    a missing index.md must rematerialize there, not only on mode 1's
    document route."""
    c, vault = client
    index = vault / "index.md"
    if index.exists():
        index.unlink()
    r = c.get("/_mdshards/api/resolve")
    assert r.json() == {"type": "md", "canonical": ""}
    assert index.exists()
    assert "Welcome to mdshards" in index.read_text()
