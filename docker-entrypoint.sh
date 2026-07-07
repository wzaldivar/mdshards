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

# Make the volume writable by the (possibly reassigned) app user. Guard on the
# top-level owner so we skip a potentially large recursive chown when it's
# already correct.
if [ "$(stat -c %u /data)" != "$UID" ] || [ "$(stat -c %g /data)" != "$GID" ]; then
  chown -R app:app /data
fi

exec gosu app "$@"
