# mdshards — live demo

The locked-down **public demo** build of [mdshards](https://github.com/wzaldivar/mdshards)
— a browser editor for a vault of plain markdown notes, synced live over CRDT.

## 🔗 Try it now: <https://mdshards-demo.wzaldivar.me>

No install needed — open the link and start editing. Everyone shares one vault.

> ### ⚠️ This is a demo, not the real thing
>
> It is deliberately restricted and **ephemeral** — do not use it for anything
> you want to keep, and do not deploy it as a real instance. For actual use,
> run the full image: **`wzaldivar/mdshards`**
> (see the [project README](https://github.com/wzaldivar/mdshards)).

## What's different from the real image

- 📝 **The landing page (`/`) is read-only** — you can type, but nothing saves.
- ⬆️ **Uploads are disabled.**
- 📎 **Assets are seeded-only.** The sample files under `attachments/` are ours;
  you can't add to or write into that directory.
- 🔗 **External links are shown but not clickable**, and **any external or
  `data:` image is replaced with a [Lorem Picsum](https://picsum.photos)
  placeholder** — the demo never renders arbitrary third-party content.
- 💾 **The whole vault is a ~20 MB RAM disk** and is **wiped on every restart**
  (the hosted demo resets on a timer). A full vault just stops accepting writes.
- Vault paths are capped at 30 characters.

Everything *else* works: create/edit/rename/delete your own `.md` notes, live
CRDT sync between everyone connected, tables, task lists, wikilinks, emoji.

## Run it yourself

```sh
# 20 MB RAM-backed, capped, ephemeral vault (no privileges needed):
docker run -d -p 8000:8000 --tmpfs /data:size=20m wzaldivar/mdshards-demo
```

Open <http://127.0.0.1:8000/>. Restarting the container resets everything — the
sample `attachments/` and the welcome page are re-seeded on start.

## Supported tags

- `latest` — always the current demo build. (The versioned, unrestricted image
  lives at [`wzaldivar/mdshards`](https://hub.docker.com/r/wzaldivar/mdshards).)

Multi-arch: `linux/amd64`, `linux/arm64`.

## License

[MIT](https://github.com/wzaldivar/mdshards/blob/main/LICENSE).
