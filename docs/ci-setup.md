# CI & analysis setup

GitHub Actions (`.github/workflows/ci.yml`) runs on every push to `main` and
every PR: backend (ruff lint + `pytest` with coverage) and frontend (`tsc`
typecheck + `vitest` with coverage). Coverage is emitted as
`backend/coverage.xml` (Cobertura) and `frontend/coverage/lcov.info` (lcov)
and uploaded to the services below.

The workflow and config files are already committed. The steps here are the
**account-side wiring** that can't live in the repo — each is one-time, and
until you do them the corresponding upload just no-ops (CI stays green).

## Codecov (coverage) — free for public repos

1. Sign in at <https://codecov.io> with GitHub and add `wzaldivar/mdshards`.
2. Copy the repo upload token, then in GitHub: **Settings → Secrets and
   variables → Actions → New repository secret**, name `CODECOV_TOKEN`.
   - Public-repo uploads work tokenless too, but the token avoids the
     occasional rate-limited/flaky upload. The workflow already passes it if
     present (`fail_ci_if_error: false`, so a hiccup never breaks the build).
3. Coverage is reported under two **flags**, `backend` and `frontend`, so each
   subproject trends independently.

## SonarCloud / SonarQube Cloud (quality + coverage) — free for public repos

1. Sign in at <https://sonarcloud.io> with GitHub, create/choose an
   organization, and import `wzaldivar/mdshards`.
2. Confirm the **organization key** and **project key** it assigns and, if they
   differ from the defaults, edit `sonar-project.properties`
   (`sonar.organization`, `sonar.projectKey` — defaults assume org `wzaldivar`,
   key `wzaldivar_mdshards`).
3. **Turn OFF "Automatic Analysis"** in the project's *Administration →
   Analysis Method* — this repo drives the scan from CI so Sonar ingests the
   real coverage reports. (The two methods are mutually exclusive.)
4. Generate a token (*My Account → Security*) and add it as the GitHub secret
   `SONAR_TOKEN`. The `sonarcloud` CI job detects the secret and activates —
   no secret means the job is a green no-op.

## Snyk (dependency + code security) — free for open source

Uses the **GitHub App**, not a CI secret — zero workflow maintenance:

1. Sign in at <https://snyk.io> with GitHub.
2. **Add project → GitHub**, select `wzaldivar/mdshards`. Snyk auto-detects
   `backend/requirements.txt` and `frontend/package.json`.
3. Enable **Snyk Open Source** (dependency CVEs) and **Snyk Code** (SAST) for
   the repo, and turn on **PR checks** + the weekly retest if you want fix PRs.

No token needed; Snyk polls the repo itself. (If you later prefer a CI-gated
scan instead, add `snyk/actions` with a `SNYK_TOKEN` secret — not wired here
on purpose, to keep the pipeline secret-light.)

## Docker Hub release (`.github/workflows/release.yml`)

Tagging `v*` (or running the workflow manually) builds the single-container
image multi-arch and pushes `wzaldivar/mdshards:<version>` + `:latest` to
Docker Hub. Two secrets are required:

1. Create a Docker Hub **access token** (Docker Hub → Account Settings →
   Personal access tokens), read/write scope.
2. Add repo secrets `DOCKERHUB_USERNAME` (`wzaldivar`) and `DOCKERHUB_TOKEN`
   (the token). Until both exist the job is a green no-op.
3. Re-publish an already-tagged version by running the **Release** workflow via
   *Actions → Release → Run workflow* with the version (e.g. `1.0.0`) — useful
   when the tag was pushed before the secrets were in place.

**Immutability guardrail:** the workflow refuses to publish a `<version>` that
already exists on Docker Hub (it queries the Hub tags API and fails the run),
so a re-tag or re-run can't silently overwrite a released version. `:latest`
always moves to the build, and a *deliberate* overwrite is possible via *Run
workflow* with `allow_overwrite = true`. The check fails open if Hub's API is
unreachable — it's a convenience rail, not a security control.

Local alternative (no CI):

```sh
docker login -u wzaldivar
docker buildx build --platform linux/amd64,linux/arm64 \
  -t wzaldivar/mdshards:1.0.0 -t wzaldivar/mdshards:latest --push .
```

### Docker Hub page description

The release workflow also syncs the Docker Hub repository overview from
`docs/dockerhub-overview.md` (and sets the short description) on each publish,
using the same `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN` secrets. This step is
**non-fatal** — Docker Hub's description API historically requires the account
*password* rather than an access token, so if it returns 401 the image publish
still succeeds. If you hit that, add a `DOCKERHUB_DESCRIPTION_TOKEN` secret set
to your account password (the workflow prefers it over `DOCKERHUB_TOKEN` for
this step only), or just paste `docs/dockerhub-overview.md` into the page by
hand.

## Badges

The README badges resolve automatically once each service is linked; before
then they render as "unknown"/"pending", which is harmless.
