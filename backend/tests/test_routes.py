def test_config_exposes_home_path_default_empty(client) -> None:
    c, _ = client
    body = c.get("/api/config").json()
    assert body["homePath"] == ""
    assert "gracePeriodSeconds" in body


def test_config_exposes_home_path_when_base_url_set(client, monkeypatch) -> None:
    monkeypatch.setenv("BASE_URL", "/wiki")
    from app import config

    config.get_settings.cache_clear()
    c, _ = client
    body = c.get("/api/config").json()
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


def test_md_url_with_literal_md_file_redirects_to_canonical(client) -> None:
    """A `.md` URL is allowed now. If the canonical doc-id form
    (`<vault>/x.md.md`) doesn't exist but the literal `<vault>/x.md` does —
    which is itself a markdown note with doc-id `x` — redirect to `/x`."""
    c, vault = client
    (vault / "x.md").write_text("hi")
    r = c.get("/x.md", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/x"


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


def test_deleted_asset_no_longer_serves(client) -> None:
    """After an asset is deleted, re-fetching its URL 404s (nothing on disk to
    revalidate against) instead of resurrecting stale bytes."""
    c, vault = client
    (vault / "gone.png").write_bytes(b"\x89PNG")
    assert c.get("/gone.png", headers={"sec-fetch-dest": "image"}).status_code == 200
    assert c.delete("/api/assets/gone.png").status_code == 200
    assert c.get("/gone.png", headers={"sec-fetch-dest": "image"}).status_code == 404


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
    r = c.post("/api/files", json={"path": "notes/hello"})
    assert r.status_code == 201
    assert (vault / "notes" / "hello.md").exists()


def test_create_file_with_content(client) -> None:
    c, vault = client
    r = c.post("/api/files", json={"path": "notes/imported", "content": "# Hi\n"})
    assert r.status_code == 201
    assert (vault / "notes" / "imported.md").read_text() == "# Hi\n"


def test_create_file_conflict(client) -> None:
    c, vault = client
    (vault / "x.md").write_text("")
    r = c.post("/api/files", json={"path": "x"})
    assert r.status_code == 409


def test_create_file_allows_spaces(client) -> None:
    c, vault = client
    r = c.post("/api/files", json={"path": "has space"})
    assert r.status_code == 201
    assert (vault / "has space.md").exists()


def test_create_file_rejects_traversal(client) -> None:
    c, _ = client
    r = c.post("/api/files", json={"path": "../escape"})
    assert r.status_code == 400


def test_delete_file_and_prune(client) -> None:
    c, vault = client
    (vault / "a").mkdir()
    (vault / "a" / "b.md").write_text("")
    r = c.delete("/api/files/a/b")
    assert r.status_code == 200
    assert not (vault / "a" / "b.md").exists()
    assert not (vault / "a").exists()


def test_move_renames_file_and_prunes_source_dirs(client) -> None:
    c, vault = client
    (vault / "old" / "nested").mkdir(parents=True)
    (vault / "old" / "nested" / "note.md").write_text("body")
    r = c.post("/api/files/move", json={"src": "old/nested/note", "dst": "new/place/note"})
    assert r.status_code == 200
    assert (vault / "new" / "place" / "note.md").read_text() == "body"
    assert not (vault / "old").exists()


def test_move_rejects_existing_destination(client) -> None:
    c, vault = client
    (vault / "a.md").write_text("")
    (vault / "b.md").write_text("")
    r = c.post("/api/files/move", json={"src": "a", "dst": "b"})
    assert r.status_code == 409


def test_move_endpoints_have_no_overwrite_escape(client) -> None:
    """INVARIANT: upload is the only operation that may overwrite — it asks
    the user and carries a declared payload. The move endpoints must 409 on
    an existing destination even if a caller smuggles an `overwrite` field
    into the body; the flag exists only on POST /api/files and /api/assets."""
    c, vault = client
    (vault / "a.md").write_text("keep a")
    (vault / "b.md").write_text("keep b")
    r = c.post("/api/files/move", json={"src": "a", "dst": "b", "overwrite": True})
    assert r.status_code == 409
    assert (vault / "b.md").read_text() == "keep b"

    (vault / "x.png").write_bytes(b"keep x")
    (vault / "y.png").write_bytes(b"keep y")
    r = c.post("/api/assets/move", json={"src": "x.png", "dst": "y.png", "overwrite": True})
    assert r.status_code == 409
    assert (vault / "y.png").read_bytes() == b"keep y"


def test_move_rejects_index(client) -> None:
    c, vault = client
    (vault / "x.md").write_text("")
    c.get("/")  # materialize index.md
    r = c.post("/api/files/move", json={"src": "index", "dst": "x_renamed"})
    assert r.status_code == 403
    r = c.post("/api/files/move", json={"src": "x", "dst": "index"})
    assert r.status_code == 403


def test_move_allows_spaces(client) -> None:
    c, vault = client
    (vault / "a.md").write_text("")
    r = c.post("/api/files/move", json={"src": "a", "dst": "with space"})
    assert r.status_code == 200
    assert (vault / "with space.md").exists()


def test_delete_index_refused(client) -> None:
    c, _ = client
    c.get("/")
    r = c.delete("/api/files/index")
    assert r.status_code == 403


def test_delete_missing_404(client) -> None:
    c, _ = client
    r = c.delete("/api/files/never/existed")
    assert r.status_code == 404


def test_tree_endpoint(client) -> None:
    c, vault = client
    (vault / "a").mkdir()
    (vault / "a" / "b.md").write_text("")
    (vault / "c.md").write_text("")
    r = c.get("/api/tree")
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
    r = c.post("/api/files", json={"path": "note", "content": "replacement"})
    assert r.status_code == 409
    assert (vault / "note.md").read_text() == "original"

    r = c.post("/api/files", json={"path": "note", "content": "replacement", "overwrite": True})
    assert r.status_code == 201
    assert (vault / "note.md").read_text() == "replacement"


def test_asset_upload(client) -> None:
    c, vault = client
    r = c.post(
        "/api/assets",
        data={"path": "notes/diagram.png"},
        files={"file": ("diagram.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    assert r.status_code == 201
    assert (vault / "notes" / "diagram.png").read_bytes().startswith(b"\x89PNG")


def test_asset_upload_collision_requires_explicit_overwrite(client) -> None:
    """An existing target 409s unless `overwrite` is set — the accept half of
    the frontend's accept-or-rename prompt. Nothing is silently replaced."""
    c, vault = client
    (vault / "pic.png").write_bytes(b"original")
    r = c.post(
        "/api/assets",
        data={"path": "pic.png"},
        files={"file": ("pic.png", b"replacement", "image/png")},
    )
    assert r.status_code == 409
    assert (vault / "pic.png").read_bytes() == b"original"

    r = c.post(
        "/api/assets",
        data={"path": "pic.png", "overwrite": "true"},
        files={"file": ("pic.png", b"replacement", "image/png")},
    )
    assert r.status_code == 201
    assert (vault / "pic.png").read_bytes() == b"replacement"


def test_asset_upload_case_variant_is_not_a_collision(client) -> None:
    """Collisions are full-filename matches with the filesystem's own
    semantics. On a case-sensitive FS `pic.PNG` lands beside `pic.png`; on a
    case-insensitive one (macOS APFS) the exists() check reports the clash
    and the upload 409s instead of clobbering. Either outcome is correct —
    the test asserts no silent overwrite ever happens."""
    c, vault = client
    (vault / "pic.png").write_bytes(b"lower")
    r = c.post(
        "/api/assets",
        data={"path": "pic.PNG"},
        files={"file": ("pic.PNG", b"upper", "image/png")},
    )
    if r.status_code == 201:  # case-sensitive filesystem: distinct files
        assert (vault / "pic.PNG").read_bytes() == b"upper"
    else:  # case-insensitive filesystem: surfaced as a collision
        assert r.status_code == 409
    assert (vault / "pic.png").read_bytes() == b"lower"


def test_asset_upload_rejects_no_extension(client) -> None:
    c, _ = client
    r = c.post(
        "/api/assets",
        data={"path": "notes/diagram"},
        files={"file": ("d", b"\x00", "application/octet-stream")},
    )
    assert r.status_code == 400


def test_asset_upload_rejects_md_path(client) -> None:
    """The asset endpoint must not write to `.md` paths — those belong to the
    CRDT layer. Without this guard, a direct caller (or a cross-origin form
    submission) could overwrite an actively-edited note out from under the
    in-memory Doc."""
    c, vault = client
    r = c.post(
        "/api/assets",
        data={"path": "notes/shadow.md"},
        files={"file": ("shadow.md", b"overwrite", "text/plain")},
    )
    assert r.status_code == 400
    assert not (vault / "notes" / "shadow.md").exists()


def test_asset_move_to_md_converts_into_note(client) -> None:
    """An asset renamed to a `.md` target (any casing) becomes a note at the
    canonical lowercase path. Whether the bytes are valid markdown is the
    user's problem; the frontend confirms before sending. This is also the
    escape hatch for stray `foo.MD` files created directly on disk."""
    c, vault = client
    (vault / "notes.MD").write_text("# stuck as asset")
    r = c.post("/api/assets/move", json={"src": "notes.MD", "dst": "notes.md"})
    assert r.status_code == 200
    assert r.json() == {"from": "notes.MD", "to": "notes", "converted": True}
    assert (vault / "notes.md").read_text() == "# stuck as asset"
    assert c.get("/api/resolve/notes").json() == {"type": "md", "canonical": "notes"}

    # Any casing of the target works and lands lowercase.
    (vault / "img.png").write_bytes(b"x")
    r = c.post("/api/assets/move", json={"src": "img.png", "dst": "img-note.MD"})
    assert r.status_code == 200
    assert r.json()["to"] == "img-note"
    assert (vault / "img-note.md").exists()


def test_asset_move_to_md_collides_with_existing_note(client) -> None:
    c, vault = client
    (vault / "taken.md").write_text("existing note")
    (vault / "data.bin").write_bytes(b"x")
    r = c.post("/api/assets/move", json={"src": "data.bin", "dst": "taken.md"})
    assert r.status_code == 409
    assert (vault / "taken.md").read_text() == "existing note"


def test_asset_move_rejects_lowercase_md_source(client) -> None:
    """A true lowercase `.md` source is a live note — it belongs to
    /api/files/move, never the asset endpoint."""
    c, vault = client
    (vault / "note.md").write_text("note")
    r = c.post("/api/assets/move", json={"src": "note.md", "dst": "note.txt"})
    assert r.status_code == 400
    assert not (vault / "shadow.md").exists()
    (vault / "shadow.md").write_text("a real note")
    r = c.post("/api/assets/move", json={"src": "shadow.md", "dst": "moved.png"})
    assert r.status_code == 400
    assert (vault / "shadow.md").exists()


def test_asset_move_renames_and_prunes(client) -> None:
    c, vault = client
    (vault / "old" / "nested").mkdir(parents=True)
    (vault / "old" / "nested" / "diagram.png").write_bytes(b"\x89PNG")
    r = c.post(
        "/api/assets/move",
        json={"src": "old/nested/diagram.png", "dst": "new/place/diagram.png"},
    )
    assert r.status_code == 200
    assert (vault / "new" / "place" / "diagram.png").read_bytes() == b"\x89PNG"
    assert not (vault / "old").exists()


def test_asset_move_rejects_existing_destination(client) -> None:
    c, vault = client
    (vault / "a.png").write_bytes(b"a")
    (vault / "b.png").write_bytes(b"b")
    r = c.post("/api/assets/move", json={"src": "a.png", "dst": "b.png"})
    assert r.status_code == 409


def test_asset_move_rejects_missing_source(client) -> None:
    c, _ = client
    r = c.post("/api/assets/move", json={"src": "missing.png", "dst": "new.png"})
    assert r.status_code == 404


def test_asset_move_rejects_extensionless_destination(client) -> None:
    c, vault = client
    (vault / "a.png").write_bytes(b"a")
    r = c.post("/api/assets/move", json={"src": "a.png", "dst": "renamed"})
    assert r.status_code == 400


def test_asset_move_rejects_extensionless_source(client) -> None:
    c, _ = client
    r = c.post("/api/assets/move", json={"src": "no_ext", "dst": "a.png"})
    assert r.status_code == 400


def test_asset_move_allows_spaces(client) -> None:
    c, vault = client
    (vault / "a.png").write_bytes(b"a")
    r = c.post("/api/assets/move", json={"src": "a.png", "dst": "with space.png"})
    assert r.status_code == 200
    assert (vault / "with space.png").exists()


def test_asset_move_same_src_dst_rejected(client) -> None:
    c, vault = client
    (vault / "a.png").write_bytes(b"a")
    r = c.post("/api/assets/move", json={"src": "a.png", "dst": "a.png"})
    assert r.status_code == 400


def test_resolve_root_is_md(client) -> None:
    c, _ = client
    r = c.get("/api/resolve")
    assert r.status_code == 200
    assert r.json() == {"type": "md", "canonical": ""}


def test_resolve_index_is_md(client) -> None:
    c, _ = client
    r = c.get("/api/resolve/index")
    assert r.status_code == 200
    assert r.json() == {"type": "md", "canonical": ""}


def test_resolve_existing_md(client) -> None:
    c, vault = client
    (vault / "notes").mkdir()
    (vault / "notes" / "today.md").write_text("hi")
    r = c.get("/api/resolve/notes/today")
    assert r.json() == {"type": "md", "canonical": "notes/today"}


def test_resolve_dotty_md(client) -> None:
    """Disk file `notes/my.weekly.md` → URL `/notes/my.weekly` resolves as md."""
    c, vault = client
    (vault / "notes").mkdir()
    (vault / "notes" / "my.weekly.md").write_text("hi")
    r = c.get("/api/resolve/notes/my.weekly")
    assert r.json() == {"type": "md", "canonical": "notes/my.weekly"}


def test_resolve_existing_asset(client) -> None:
    c, vault = client
    (vault / "notes").mkdir()
    (vault / "notes" / "diagram.png").write_bytes(b"\x89PNG")
    r = c.get("/api/resolve/notes/diagram.png")
    assert r.json() == {"type": "asset", "canonical": "notes/diagram.png"}


def test_resolve_md_wins_over_existing_asset(client) -> None:
    """`foo.jpg.md` exists alongside `foo.jpg` — md wins per the rule."""
    c, vault = client
    (vault / "foo.jpg.md").write_text("the note about the picture")
    (vault / "foo.jpg").write_bytes(b"\xff\xd8\xff")
    r = c.get("/api/resolve/foo.jpg")
    assert r.json() == {"type": "md", "canonical": "foo.jpg"}


def test_resolve_md_url_falls_back_to_canonical(client) -> None:
    """URL `foo.md` with no `<vault>/foo.md.md` but with `<vault>/foo.md`
    on disk: the literal file is itself an md note with doc-id `foo`.
    Canonical URL is `/foo`."""
    c, vault = client
    (vault / "foo.md").write_text("hi")
    r = c.get("/api/resolve/foo.md")
    assert r.json() == {"type": "md", "canonical": "foo"}


def test_resolve_md_url_with_nested_md_md(client) -> None:
    """When `<vault>/foo.md.md` exists, `/foo.md` is canonical (doc-id is
    `foo.md`, no `.md` to strip from the URL)."""
    c, vault = client
    (vault / "foo.md.md").write_text("doc-id is foo.md")
    r = c.get("/api/resolve/foo.md")
    assert r.json() == {"type": "md", "canonical": "foo.md"}


def test_resolve_missing(client) -> None:
    c, _ = client
    r = c.get("/api/resolve/no/such/thing")
    assert r.json() == {"type": "missing", "canonical": "no/such/thing"}


def test_resolve_missing_dotty(client) -> None:
    c, _ = client
    r = c.get("/api/resolve/no/such/thing.png")
    assert r.json() == {"type": "missing", "canonical": "no/such/thing.png"}


def test_resolve_missing_md_url_canonicalizes(client) -> None:
    """A `.md` URL with no on-disk match falls through to the canonical
    extensionless form (which is also missing). The frontend will redirect
    `/foo.md` → `/foo` and then show NotFound at the canonical address."""
    c, _ = client
    r = c.get("/api/resolve/no.md")
    assert r.json() == {"type": "missing", "canonical": "no"}


def test_resolve_allows_spaces(client) -> None:
    c, vault = client
    (vault / "with space.md").write_text("")
    r = c.get("/api/resolve/with space")
    assert r.status_code == 200
    assert r.json() == {"type": "md", "canonical": "with space"}
