#!/usr/bin/env bash
#
# Create (or reset) a fixed-size ext4 filesystem image and mount it, to back the
# mdshards *demo* vault. The vault then lives on a filesystem whose TOTAL size
# is hard-capped: a full vault returns ENOSPC to the app instead of eating the
# host disk. Pair it with the demo image (read-only landing page, uploads off,
# attachments/ locked) and a periodic --reset for the "wipes every 2h" story.
#
# Mount it into the container as /data (covers both the vault and the CRDT
# cache, so the whole app footprint is capped):
#
#     sudo SIZE_MB=20 ./demo-vault-fs.sh          # create + mount
#     docker run -d -p 8000:8000 \
#         -v /srv/mdshards-demo/data:/data wzaldivar/mdshards:demo
#     sudo ./demo-vault-fs.sh --reset             # wipe back to an empty cap
#
# Linux host only (loop device + mkfs.ext4), run as root. Env overrides:
#   SIZE_MB   cap in MiB            (default 20)
#   IMG       backing image file    (default /srv/mdshards-demo/data.img)
#   MNT       mount point           (default /srv/mdshards-demo/data)
#   APP_UID / APP_GID  owner to match the container user (default 1000:1000;
#             set these if you run the container with its UID/GID remap vars)
#
set -euo pipefail

SIZE_MB="${SIZE_MB:-20}"
IMG="${IMG:-/srv/mdshards-demo/data.img}"
MNT="${MNT:-/srv/mdshards-demo/data}"
APP_UID="${APP_UID:-1000}"
APP_GID="${APP_GID:-1000}"

die() { echo "demo-vault-fs: $*" >&2; exit 1; }

[ "$(uname -s)" = "Linux" ] || die "Linux only (needs loop devices + mkfs.ext4)"
[ "$(id -u)" = "0" ] || die "must run as root (loop mount + mkfs need it)"
command -v mkfs.ext4 >/dev/null 2>&1 || die "mkfs.ext4 not found — install e2fsprogs"

reset=0
case "${1:-}" in
  "") ;;
  --reset) reset=1 ;;
  *) die "unknown argument: $1 (only --reset)" ;;
esac

mkdir -p "$(dirname "$IMG")" "$MNT"

# Already mounted? No-op unless resetting, in which case unmount first.
if mountpoint -q "$MNT"; then
  [ "$reset" = 0 ] && { echo "already mounted at $MNT"; exit 0; }
  umount "$MNT"
fi

# (Re)create the image only when resetting or when it doesn't exist yet, so a
# plain run after a host reboot re-mounts the SAME data. The image is a fixed
# size; the ext4 on top can never grow past it — that's the cap.
if [ "$reset" = 1 ] || [ ! -f "$IMG" ]; then
  rm -f "$IMG"
  truncate -s "${SIZE_MB}M" "$IMG"
  mkfs.ext4 -q -F -m 0 "$IMG"   # -m 0: no root-reserved blocks, use the full cap
fi

mount -o loop "$IMG" "$MNT"
# The container's app user owns the data dirs; match it so writes work. The
# entrypoint also chowns on start, but setting it here avoids a first-boot race.
chown "$APP_UID:$APP_GID" "$MNT"

avail="$(df -h --output=size "$MNT" | tail -1 | tr -d ' ')"
echo "mounted ${SIZE_MB}MB ext4 vault fs at: $MNT  (df size: ${avail})"
echo "docker run -d -p 8000:8000 -v \"$MNT\":/data wzaldivar/mdshards:demo"
