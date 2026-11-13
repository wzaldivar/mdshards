# Fuzzing

[Atheris](https://github.com/google/atheris) targets for the backend's
security- and data-integrity-critical pure functions, built with the
OSS-Fuzz toolchain.

| Target | Under test | Invariant |
| --- | --- | --- |
| `fuzz_vault_path` | `vault.resolve_md`, `resolve_asset` (the app's only two entry points into the vault) | a URL either raises `VaultPathError` or resolves inside the vault, against a fixture vault containing escaping, dangling, and in-vault symlinks; a URL with a null byte, a backslash, a `..` segment or the reserved `_mdshards` first segment always raises |
| `fuzz_merge` | `DocumentManager._three_way_merge`, `_apply_ghost_merge` | merge identities hold; ghost splices turn the `Y.Text` into exactly the target, multibyte text included, and never panic pycrdt |
| `fuzz_origin_guard` | `security.is_request_allowed`, `api_request_allowed` | never raises on arbitrary header bytes; cross-site is always rejected; a request with no fingerprint never passes `/api`; a same-origin request does |

## Where they run

- **ClusterFuzzLite**, on every PR touching `backend/` (`.github/workflows/fuzz.yml`).
  The build lives in `.clusterfuzzlite/`; its `build.sh` is the single build
  script, which OSS-Fuzz reuses.
  The result is posted as a PR comment by `.github/scripts/pr_report.py`: for
  a broken invariant, the call that was made, what it returned and what was
  expected, plus the trace and reproducer; or a clean bill.

## Reporting a broken invariant

Raise through the target's `_fail(called, got, expected)` rather than a bare
`AssertionError`. Its three labelled lines are what the PR comment shows, so
write them for a reader who hasn't seen the target: the real function call
with its arguments, the actual result, and the required result with the rule
in parentheses. Name the function the app itself calls (`resolve_md`), not a
private helper behind it (`_validate`) — the report should point at code a
reader can find a caller for. `_fail` is repeated in each target on purpose — each one is
packaged as a standalone executable, so a shared helper module is one more
thing for the build to lose.
- **OSS-Fuzz**: `oss-fuzz/` holds the `projects/mdshards/` files to submit to
  [google/oss-fuzz](https://github.com/google/oss-fuzz). Its
  `primary_contact` is the Google account that gets the ClusterFuzz dashboard
  and bug reports.

Both Dockerfiles install Python 3.14 over the builder's 3.11, because the
backend won't parse on 3.11. Keep their toolchain pins in lockstep.

## Running locally

Atheris ships wheels only for Linux x86_64, so you can't run it natively on
macOS. Use the OSS-Fuzz images (needs Docker; on Apple Silicon they run under
amd64 emulation):

```sh
docker build --platform linux/amd64 -t mdshards-fuzz -f .clusterfuzzlite/Dockerfile .
docker run --rm --platform linux/amd64 -e SANITIZER=address -e FUZZING_LANGUAGE=python \
  -e FUZZING_ENGINE=libfuzzer -e ARCHITECTURE=x86_64 -v mdshards-fuzz-out:/out mdshards-fuzz compile
docker run --rm --platform linux/amd64 -v mdshards-fuzz-out:/out gcr.io/oss-fuzz-base/base-runner \
  /out/fuzz_merge -max_total_time=60
```

Under emulation the ASan-preloading wrapper (`/out/<target>`) is killed at
startup, because Rosetta can't map ASan's shadow memory. Run the bundle
directly instead: `chmod +x /out/<target>.pkg && /out/<target>.pkg`. On a
real x86_64 host, use `/out/<target>` as usual.

On a Linux x86_64 host with Python 3.14, run from `backend/`:
`pip install atheris && PYTHONPATH=. python fuzz/fuzz_merge.py`.
