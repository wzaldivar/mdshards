# Testing

Three tiers, run independently. All three gate CI (`.github/workflows/ci.yml`); see [operations/deployment](operations/deployment.md#ci--release-workflows).

## Backend — pytest (`backend/tests/`)

From `backend/`:

```bash
pip install -r requirements-dev.txt
pytest                                   # all
pytest tests/test_vault.py::<test_name>  # one
ruff format backend/ && ruff check backend/
```

Test files map to the service modules: `test_vault.py` (path-traversal boundary), `test_security.py` (origin guard), `test_docs.py` (doc lifecycle, flush, conflict merge, blob cache), `test_watcher.py` (external-writer reconciliation + a real-`watchdog`-observer end-to-end test), `test_files.py`, `test_tree.py`, `test_routes.py`, `test_config.py`, `test_ws.py`. Shared fixtures in `conftest.py`.

The conflict-merge tests are the sharp edge: `test_docs.py` covers flush/conflict-file/cache behavior, and `test_watcher.py` exercises `_three_way_merge` region classification and both reconciliation directions ([sync-and-crdt](architecture/sync-and-crdt.md#conflict-policy--one-unified-line-based-3-way-merge)).

## Frontend — vitest (`frontend/src/__tests__/`, `frontend/src/lib/__tests__/`)

From `frontend/`:

```bash
npm install
npm run test          # vitest
npm run build         # production build
npx tsc -b            # typecheck (CI runs this)
```

Covers the switchers, editor shortcuts, `markdown-live` decorations, path/url helpers, and the emoji picker. After any switcher/editor change, verify the keyboard chords by hand on both a `.md` URL and an asset URL — they've regressed repeatedly.

## End-to-end — Playwright, multi-engine, containerized (`e2e/`)

Real browsers against the shipping image, fully containerized via **docker compose** (not testcontainers). Needs a running Docker daemon (`colima start` locally).

```bash
docker compose -f e2e/docker-compose.e2e.yml build
docker compose -f e2e/docker-compose.e2e.yml run --rm tests
docker compose -f e2e/docker-compose.e2e.yml down -v   # always, to drop vault volumes
```

The shipping image runs as `app-root` / `app-wiki` (`BASE_URL=/wiki`) / `app-perms` (root-owned split mounts) services; the suite runs inside the official Playwright image as the `tests` service and drives **Chromium + Firefox + WebKit** by service name over the compose network. The vault is a shared named volume, so the external-writer role (`seed_vault_file` / `read_vault_file` / `wait_vault_file` in `conftest.py`) is a direct filesystem write. Suites: `test_root_mount.py`, `test_subpath_mount.py`, `test_switchers.py`, `test_markdown_rendering.py`, `test_embedded_images.py`, `test_asset_refresh.py`, `test_mount_permissions.py`.

Prefer adding an e2e journey over a unit-level fetch when a change touches deployment behavior (routing, prefixes, the shell, the origin guard).

### Gotchas to know

- **Engine-unique vault paths.** A journey that seeds-then-mutates a note must use an engine-unique path (e.g. `swg/note-{browser_name}`); a shared path races the grace-period in-memory doc across the sequential engine runs — it passes on the first engine and fails on later ones with stale disk content. The rename journey documents the pattern.
- **WebKit flakiness.** Timing-sensitive content-load assertions (e.g. quick-switcher navigation) occasionally flake on WebKit under CI load — re-run the failed job before assuming a regression. Playwright headless WebKit also does **not** reproduce real-Safari style-invalidation bugs; confirm Safari-specific fixes in a real Safari build.
- **Firefox PNG decoder is stricter** than Blink/WebKit — image fixtures must be byte-valid (`make_png`, not a hand-rolled blob).
- **After a test migration/rewrite, diff the `def test_` inventory** old vs new — a rewrite can silently drop a test while the suite stays green.
