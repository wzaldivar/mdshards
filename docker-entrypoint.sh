#!/bin/sh
# Reconcile the unprivileged `app` user with a host-supplied UID/GID, fix the
# data volume's ownership, then drop privileges and exec the CMD.
#
# Why: the image ships a default app user (1000:1000), but a bind-mounted
# `-v <host-dir>:/data` keeps the host's ownership. Setting `UID`/`GID` at run
# time (`docker run -e UID=$(id -u) -e GID=$(id -g) ...`) makes the container
# user match the host owner so reads/writes to the vault just work — no rebuild.
#
# This runs as root ONLY for the remap + chown; the app itself runs as `app`.
set -e

# Defaults keep the image's baked-in ids. `/bin/sh` here is dash, where UID is
# an ordinary variable (not the readonly special bash exposes), so reading an
# env-supplied UID is safe.
: "${UID:=1000}"
: "${GID:=1000}"

if [ "$(id -g app)" != "$GID" ]; then
  groupmod -o -g "$GID" app
fi
if [ "$(id -u app)" != "$UID" ]; then
  usermod -o -u "$UID" app
fi

# DEMO: (re)seed the read-only attachments/ directory from the baked sample
# assets on every start, so the demo's landing image resolves even after the
# 2h vault wipe. Done before the chown below so a freshly-created vault dir
# gets its ownership fixed too. No-op when the seed dir isn't in the image.
if [ -d /app/demo-assets ]; then
  mkdir -p /data/vault/attachments
  cp -R /app/demo-assets/. /data/vault/attachments/
fi

# Make the data dirs writable by the (possibly reassigned) app user. Check
# /data AND the nested mount points individually: compose files commonly bind
# the vault and cache separately (`/host/vault:/data/vault`,
# `./cache:/data/cache`), and then /data itself is the image layer — already
# owned by app — so a guard on /data alone skips the chown and leaves the
# actual mounts host-owned and unwritable. Per-dir guards still skip the
# potentially large recursive chown when ownership is already correct.
for dir in /data /data/vault /data/cache; do
  [ -d "$dir" ] || continue
  if [ "$(stat -c %u "$dir")" != "$UID" ] || [ "$(stat -c %g "$dir")" != "$GID" ]; then
    chown -R app:app "$dir"
  fi
done

exec gosu app "$@"
