# syntax=docker/dockerfile:1.7
#
# Single-container deployment for mdshards.
#
# Layout:
#   stage 1  build the React/Vite frontend with Node 24
#   stage 2  Python 3.14 runtime, copies the prebuilt dist/ in and runs uvicorn
#
# uvicorn is the only process. It serves /assets/* and the two top-level
# bundle files (favicon.svg, icons.svg) straight from the copied dist/, and
# the catch-all router in app/routers/pages.py returns the real dist/index.html
# as the SPA shell. /api/* and /ws/* are routed by the existing FastAPI
# routers on the same port — no extra reverse proxy.
#
# Only port 8000 is exposed; the REST/WS handlers are reachable only via
# uvicorn itself (no separately addressable backend port).

# ---------- stage 1: build the frontend ----------
FROM node:24-alpine AS frontend-builder

WORKDIR /build

# Install deps first so the layer caches across source edits.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ---------- stage 2: runtime ----------
FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# `gosu` lets the root entrypoint drop to the unprivileged app user after
# reconciling its UID/GID with the host (see docker-entrypoint.sh).
# `e2fsprogs` + `mount` (util-linux) let the entrypoint back /data with a
# fixed-size loop-mounted ext4 image when CAP_FS_MB is set — the demo's hard
# disk cap (needs a privileged container; a no-op otherwise).
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu e2fsprogs mount \
    && rm -rf /var/lib/apt/lists/*

# Python deps first so source-only edits don't bust the wheel cache.
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

# Backend source.
COPY backend/app ./app

# Prebuilt frontend. app/config.py serves it automatically from this `static/`
# dir next to the app package — it's a fixed convention, no env var needed.
COPY --from=frontend-builder /build/dist ./static

# DEMO: read-only sample assets. The entrypoint seeds these into the vault's
# `attachments/` directory on every start (the demo vault is wiped every 2h),
# so the landing page's `attachments/sample01.jpg` always resolves.
COPY demo-assets/ ./demo-assets/

# Runtime config. Vault and CRDT cache live on a single mounted volume so a
# `docker run -v <host-dir>:/data ...` keeps both portable.
ENV VAULT_DIR=/data/vault \
    CACHE_DIR=/data/cache \
    HOST=0.0.0.0 \
    PORT=8000

# Create the unprivileged runtime user with default ids 1000:1000. The
# entrypoint can remap these at runtime via the UID/GID env vars, so the same
# image lines up with any host's file ownership on a bind mount. /data is
# created and chowned BEFORE the volume is declared so anonymous/named volumes
# inherit the ownership.
RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid 1000 --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown -R app:app /app /data

# Declare the app user's home explicitly so `~` is unambiguous. The index seed
# override is read from `~/.mdshards/index.md` (see app/files.py), i.e.
# /app/.mdshards/index.md in this image — bind-mount a file there to customize
# the auto-created index.md:
#   docker run -v ./my-index.md:/app/.mdshards/index.md ... mdshards
# gosu doesn't set HOME when it drops privileges, so without this Python's
# expanduser() would fall back to the passwd DB; pinning it keeps `~` explicit.
ENV HOME=/app

# The entrypoint runs as root only to reconcile the app user's UID/GID and fix
# volume ownership, then execs the CMD as the unprivileged app user via gosu.
COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# NOTE (demo branch): no `VOLUME ["/data"]`. The demo is deliberately ephemeral
# — /data is backed either by a fixed-size loop-mounted ext4 image the
# entrypoint creates in this (throwaway) writable layer when CAP_FS_MB is set,
# or just the writable layer itself. Either way `docker compose down && up`
# recreates the container and resets the vault. An auto anonymous volume here
# would also make /data a mountpoint and defeat the loop-mount cap. Explicit
# `-v` mounts (e.g. the e2e compose) still work regardless.

EXPOSE 8000

# uvicorn binds 0.0.0.0:8000 — the only externally reachable surface. The
# /api and /ws routers ride on the same port (they have to: the browser hits
# them after loading the bundle), but there is no separately addressable
# backend port. The entrypoint drops to the app user before this runs.
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
