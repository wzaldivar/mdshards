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
