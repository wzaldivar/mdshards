# e2e flake log

A running record of e2e (`docker-compose.e2e.yml`) failures that turned out to be **timing flakes**, not real regressions. The point is verification: every entry here failed once and then **passed verbatim on re-run of the same commit** — that's the evidence it was a timing issue. If a test ever fails *twice* on the same commit, it does **not** belong here; treat it as a real regression and investigate.

## Why these happen

The suite runs Chromium + Firefox + WebKit in parallel inside one container against the shipping image. Asserting a note's body after a navigation waits on a chain — editor mount → WebSocket connect → CRDT sync → CodeMirror render — that is sub-second on Chromium/Firefox but spikes on **WebKit under that parallel-engine CI load**. When the spike exceeds the expect timeout, the assertion flakes.

Mitigation in place: post-navigation content assertions use `expect_editor_contains` / `expect_note_text` (`conftest.py`), which wait with the longer `CRDT_LOAD_TIMEOUT` (30s) instead of the 15s default. If a WebKit content-load flake recurs *after* this mitigation, the timeout is no longer the whole story — log it and dig deeper (real slowdown, a sync regression, or a missing readiness signal).

## Policy

1. e2e job red? Look at which test/engine failed.
2. If it's a content-load assertion on WebKit (or another plausibly-timing wait), **re-run the failed job once** (`gh run rerun <run-id> --failed`).
3. Passed on re-run → add a row below and proceed. Failed again → it's real; do not merge, investigate.

## Log

| Date (UTC) | Test | Engine | PR | Run ID | Failed at | Re-run | Notes |
|---|---|---|---|---|---|---|---|
| 2026-07-17 | `test_switchers.py::test_quick_switcher_navigates_to_existing_note` | webkit | #41 | 29584813411 | `.cm-content` never contained `swq-target-body` (15s) | passed | Release 1.5.0 PR (sync/emoji). Content-load timeout; unrelated to the diff. |
| 2026-07-17 | `test_root_mount.py::test_formerly_reserved_names_are_vault_paths` | webkit | #42 | 29588777416 | content-load after navigation (15s) | passed | Docs-only PR — could not affect runtime, so unambiguously a flake. Motivated the `CRDT_LOAD_TIMEOUT` hardening. |
| 2026-09-18 | `test_switchers.py::test_shortcut_fires_from_inside_asset_iframe` | firefox | #57 | 35346572943 | `Locator.click` timeout (30s) inside the asset iframe | passed | Tests-only PR (no source in the image changed), and the same suite passed on the PR run — so nothing in the diff could reach it. First logged flake on **Firefox** rather than WebKit, and an interaction wait rather than a content-load one, so `CRDT_LOAD_TIMEOUT` is not the lever here. Watch it: a recurrence means the iframe click path needs a real readiness signal. |
| 2026-10-19 | `test_asset_refresh.py::test_overwritten_asset_shows_fresh_pixels_on_spa_navigation` | chromium | #79 | 39293174931 | `.cm-content` never visible (15s) after `_switcher_goto(page, "")` — page stayed on the AssetViewer (`img "viewer/rotating.png"`) | passed | CI-only PR (actions/checkout v4→v7); the image under test is built from the same tree regardless of checkout version, and the same commit passed e2e on its earlier PR run. First flake on **Chromium**, and the first test in the suite. The switcher's jump *out of the asset view* never navigated — an interaction failure, not a content-load one. |
| 2026-10-19 | `test_switchers.py::test_quick_switcher_navigates_to_existing_note` | webkit | main (#79 merge) | 39294034182 | URL never matched `/swq/target$` (switcher navigation didn't happen) | passed | Same CI-only change as above; main runs for #77/#78 (same app code) were green. **Second** entry for this test (2026-07-17 was a content-load timeout; this one is the navigation itself). With the row above and the 2026-09-18 iframe entry, that's three switcher/interaction-path flakes no `CRDT_LOAD_TIMEOUT` can fix — the switcher likely needs a readiness signal (input mounted + focused, tree loaded) before the test types/confirms. |
