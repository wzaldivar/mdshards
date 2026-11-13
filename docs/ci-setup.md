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
5. The job **fails when the quality gate is red** (`sonar.qualitygate.wait`
   in `sonar-project.properties`). For the gate summary as a PR comment,
   install the SonarQube Cloud GitHub App on the repo and make sure the
   project is bound to it — that decoration comes from the app, not from CI.

## OSV-Scanner (dependency vulnerabilities) — no account

`.github/workflows/osv-scanner.yml` scans the dependency manifests against
<https://osv.dev> on every push to `main`, every PR, and weekly. Nothing to
wire: no token, no external dashboard.

- A finding **fails the run** — a red check on the PR, or GitHub's
  failed-workflow email for the weekly run.
- Runs on `main` also publish the findings as alerts under **Security → Code
  scanning** (filter `tool:osv-scanner`). Same-repo PRs publish too, which
  adds a **Code scanning results** check listing the alerts on the PR; fork
  and Dependabot PRs have no write token, so they only get the pass/fail.
- `backend/requirements.txt` is unpinned, so the workflow first installs it
  and scans the frozen result (`backend-resolved-requirements.txt` in the
  alerts) — the versions a fresh image build would get that day.
- To accept a finding, add an `[[IgnoredVulns]]` entry (id + reason) to an
  `osv-scanner.toml` next to the affected manifest.

Run it locally with `osv-scanner scan source --no-resolve -r .`.

## Docker Hub + GHCR release (`.github/workflows/release.yml`)

Tagging `v*` (or running the workflow manually) builds the single-container
image multi-arch and pushes four tags to Docker Hub: the rolling `X`, `X.Y`,
and `latest` (overwritten each release to track the newest matching build) plus
the immutable `X.Y.Z`. The same build is pushed with the same four tags to
**`ghcr.io/wzaldivar/mdshards`** — one build, so both registries serve the
same digest. GHCR needs no secret (the job's `GITHUB_TOKEN` has
`packages: write`). Docker Hub needs two secrets:

1. Create a Docker Hub **access token** (Docker Hub → Account Settings →
   Personal access tokens), read/write scope.
2. Add repo secrets `DOCKERHUB_USERNAME` (`wzaldivar`) and `DOCKERHUB_TOKEN`
   (the token). Until both exist the job is a green no-op.
3. Re-publish an already-tagged version by running the **Release** workflow via
   *Actions → Release → Run workflow* with the version (e.g. `1.0.0`) — useful
   when the tag was pushed before the secrets were in place.

**Immutability guardrail:** the workflow refuses to publish an `X.Y.Z` that
already exists on Docker Hub (it queries the Hub tags API and fails the run),
so a re-tag or re-run can't silently overwrite a released version. Only `X.Y.Z`
is guarded — the rolling `X`, `X.Y`, and `latest` tags are meant to move every
release. A *deliberate* `X.Y.Z` overwrite is possible via *Run workflow* with
`allow_overwrite = true`. The check fails open if Hub's API is unreachable — it's
a convenience rail, not a security control.

Local alternative (no CI):

```sh
docker login -u wzaldivar
docker buildx build --platform linux/amd64,linux/arm64 \
  -t wzaldivar/mdshards:1.0.0 -t wzaldivar/mdshards:latest --push .
```

### GHCR backfill (`.github/workflows/ghcr-backfill.yml`)

Versions released before GHCR mirroring can be copied over without a rebuild:
*Actions → GHCR backfill → Run workflow* with the version, ticking **rolling**
only for the newest release (it repoints ghcr's `X` / `X.Y` / `latest`).
`imagetools create` copies the multi-arch index registry-to-registry, and the
run fails unless the ghcr.io digest equals Docker Hub's.

**One-time:** a package first published from Actions may start **private**.
If an anonymous `docker pull ghcr.io/wzaldivar/mdshards` is denied, set it
public under the package's *Package settings → Change visibility* (the API
can't change container visibility).

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
