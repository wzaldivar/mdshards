# Frontend architecture

A React 19 + TypeScript SPA under `frontend/src/`, built with Vite, routed with `react-router` v7, styled with CSS Modules. The editor is CodeMirror 6 bound to a `Y.Doc` synced via `y-websocket`. Entry point `main.tsx`.

**Core rule:** the frontend is stateless beyond the live CRDT doc in memory — **no persistent client storage** except small, non-vault editor UI preferences (see [domain/concepts](domain/concepts.md#no-client-database)).

## Routing

`App.tsx` is the route table: `/index` → `<Navigate to="/" replace>` (mirrors the root-index canonicalization), everything else (`*`) → `<EditorView>`. `router.ts::routeToDocId()` maps the splat param to a doc-id. The `<BrowserRouter basename>` comes from `/api/config`'s `homePath` (the `BASE_URL` sub-path) — the *only* thing that value drives.

`views/EditorView.tsx` is the catch-all component: it resolves the current path via `lib/use-resolve.ts` (the client side of the md-vs-asset rule, calling `GET /api/resolve/{path}`) and hosts the editor, the `AssetViewer`, or `NotFound`. `components/Editor.tsx` is its child.

## The editor & live preview

`components/Editor.tsx` builds the CodeMirror view and binds it to the CRDT doc. The live-preview decorations — rendering raw markdown as formatted when the cursor is elsewhere, revealing raw source when touched — live in `lib/markdown-live.ts`, with markdown extensions in `lib/md-highlight.ts`, `lib/md-emoji.ts` (`:shortcode:` parser), `lib/cm-highlight.ts`, and `lib/wikilink.ts`.

Two behavioral rules to preserve (see [`FEATURES.md`](../FEATURES.md)):
- **Touch = plain text.** The moment the cursor hits a rendered region, it becomes a plain-text editor there: raw revealed, char-wise movement/deletion, no atomic leaps over touched content.
- **No in-buffer autocomplete popups.** Discovery/insertion happens in modal pickers, never completion UI over the buffer.

Editor UI preferences (vim mode, line numbers, relative line numbers, typewriter/center-line) persist to `localStorage` under `mdshards:*` keys via `lib/editor-prefs.ts` (with a pub/sub the live editor subscribes to) — the one sanctioned exception to "no client storage." `lib/typewriter.ts` implements center-current-line scrolling.

## CRDT client (`lib/crdt.ts`)

Wires the `Y.Doc`, `y-websocket` provider, and `y-codemirror.next` binding. This is the client half of [sync-and-crdt](sync-and-crdt.md) and must stay in lockstep with `backend/app/ws.py` on the wire format. It also owns the reconnect behavior: a periodic awareness heartbeat keeps a resident tab's doc alive, and on a past-grace reconnect the local doc is **dismissed and re-synced from scratch**, never merged.

## The single URL choke point (`lib/backend.ts`)

**Every** runtime URL is built here — never hand-concatenate a prefix. Two helpers enforce the split:
- **`apiUrl(...)`** builds app-surface URLs (adds `/_mdshards`): `/api/*`, `/ws/*`, the bundle, the favicon.
- **`backendUrl(...)` / `backendWsUrl(...)`** build vault-content URLs (never add `/_mdshards`) — a vault asset in an `api/` folder is a legitimate `/api/pic.png` and must not be misrouted.

The `BASE_URL` sub-path is read from an injected `<meta name="mdshards-home-path">` (see [operations/deployment](operations/deployment.md)), which also solves the bootstrap problem of needing `/api/config` to learn the prefix `/api/config` itself lives under. The prefix is **never** baked at build time.

`lib/paths.ts` handles vault-path validation (`validateVaultPath`, mirroring `vault.py`) and percent-encoding at the URL boundary (`encodePathToUrl`); `lib/tree.ts` is the vault-listing client; `lib/config.ts` fetches `/api/config`; `lib/asset-kind.ts`, `lib/upload-path.ts`, `lib/pending-rename.ts`, `lib/no-autofill.ts` are supporting helpers.

## The keyboard-first switchers

The UI is keyboard-first. `lib/shortcuts.ts` registers a global capture-phase keymap; `lib/use-list-navigation.ts` is the shared Escape/arrows/Enter contract; `components/SwitcherShell.tsx` is the shared modal chrome. The quartet:

| Chord | Component | Action |
|---|---|---|
| `Cmd/Ctrl-K` | `QuickSwitcher` | Go to / create a note (the **only** UI that implicitly creates files + parent dirs). |
| `Cmd/Ctrl-Shift-K` | `RenameSwitcher` | Rename the current note. |
| `Cmd/Ctrl-Backspace` | `DeleteSwitcher` | Delete a file (always confirms; `index.md` excluded). |
| `Cmd/Ctrl-U` | `UploadSwitcher` | Upload a file (dispatch by source extension: `.md` → note, else asset). |
| `Cmd/Ctrl-E` | `EmojiSwitcher` | Emoji picker: Enter inserts `:shortcode:`, **Shift-Enter inserts the literal glyph** (added 1.5.0). |
| `Cmd/Ctrl-Alt-O` | `OptionsPanel` | Editor prefs (vim/line numbers/etc.). |

## Where to start / what to watch

- These shortcuts have regressed repeatedly — after touching a switcher, verify all chords still fire on **both** a `.md` URL and an asset URL (`AssetViewer` re-binds the handler inside its iframe).
- Never bake the `BASE_URL` prefix into the build or hand-concatenate it; route it through `backend.ts` (fetched URLs) or the router basename (pathnames).
- Frontend tests: `frontend/src/__tests__/` and `frontend/src/lib/__tests__/` (vitest); see [testing](../testing.md).
