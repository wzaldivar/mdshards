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

## Badges

The README badges resolve automatically once each service is linked; before
then they render as "unknown"/"pending", which is harmless.
