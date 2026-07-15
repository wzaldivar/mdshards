# mdshards

A SilverBullet-inspired editor for a vault of plain markdown notes. A FastAPI
server owns the vault as `.md` files on disk (no database); a React 19 +
CodeMirror 6 SPA edits them with live CRDT sync over WebSocket. Built for
editing the notes on your LAN server straight from the browser.

**Source & full docs:** https://github.com/wzaldivar/mdshards

---

## ⚠️ Know what you're running

There is **no authentication**. Anyone who can reach the server gets full
read/write access to the vault — this is like exposing a VS Code instance to
the world over your filesystem. There is no read-only or "safe to browse"
mode. **Run it on a trusted network only.**

## Supported tags

- `latest` — the newest release.
- `X` / `X.Y` — rolling tags that always point at the newest release in that
  major / major-minor line.
- `X.Y.Z` — the exact, immutable version published for each release.

Browse all tags on [Docker Hub](https://hub.docker.com/r/wzaldivar/mdshards/tags),
or see the [GitHub releases](https://github.com/wzaldivar/mdshards/releases).

Multi-arch: `linux/amd64`, `linux/arm64`.

## Quick start

```sh
docker run -p 8000:8000 -v "$(pwd)/data":/data wzaldivar/mdshards
```

Open <http://127.0.0.1:8000/>. On first hit, `index.md` is created from a
template — edit it and everything is saved as plain markdown under the mounted
volume. uvicorn is the only process: it serves the SPA, assets, REST API, and
the CRDT WebSocket on one port. No reverse proxy needed.

Match the container user to the host owner of a bind-mounted vault (so it can
write) with `UID`/`GID` — no rebuild:

```sh
docker run -p 8000:8000 -e UID=$(id -u) -e GID=$(id -g) \
  -v "$(pwd)/data":/data wzaldivar/mdshards
```

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `VAULT_DIR` | `/data/vault` | Where the `.md` vault lives. |
| `CACHE_DIR` | `/data/cache` | CRDT (`.yjs`) cache root. |
| `GRACE_PERIOD_SECONDS` | `30` | How long a doc lingers in memory after the last client disconnects. |
| `BASE_URL` | *(unset)* | Sub-path mount behind a reverse proxy, e.g. `/wiki`. |
| `UID` / `GID` | `1000` | Remap the app user to match a bind-mounted vault's owner. |

- **Volume:** `/data` — holds `/data/vault` and `/data/cache`. Mount it to
  persist notes across container restarts.
- **Port:** `8000`.
- **Runs unprivileged:** the entrypoint remaps `UID`/`GID` and fixes `/data`
  ownership as root, then drops to the app user — uvicorn never runs as root.

### Custom home page

`index.md` is seeded from a built-in template on first access. Bind-mount your
own to override the seed:

```sh
docker run -p 8000:8000 -v "$(pwd)/data":/data \
  -v "$(pwd)/my-index.md":/app/.mdshards/index.md wzaldivar/mdshards
```

## The vault is just files

Notes are plain `.md` on disk — no database, no lock-in. The vault stays fully
portable (edit it with Obsidian, sync it with Syncthing, grep it, back it up),
which is the whole point. mdshards also folds in external changes to open notes
while you edit.

## License

[MIT](https://github.com/wzaldivar/mdshards/blob/main/LICENSE).
