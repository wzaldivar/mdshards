# Features

Living inventory of what `mdshards` does today, what it could grow into, and
what it deliberately won't. Section structure mirrors the
[markdownguide.org](https://www.markdownguide.org) basic / extended pages
plus project-specific additions and editor capabilities.

## Markdown syntax

### Basic syntax

Reference: [markdownguide.org/basic-syntax](https://www.markdownguide.org/basic-syntax/).

**Supported**

- Headings — ATX (`#` … `######`) and Setext (`Heading\n===` / `Heading\n---`). ATX headings require blank-line context above and below; otherwise the `#` is preserved as literal text.
- Paragraphs.
- Hard line breaks — the editor preserves source line breaks as-is, so the two-trailing-spaces and bare-newline forms both work.
- Bold (`**` and `__`) and Italic (`*` and `_`). Intra-word underscore rule honored — `last_charged_at` stays literal; `**foo_bar**` and `__foo_bar__` render as bold.
- Bold + Italic (`***`).
- Blockquotes including nested and multi-paragraph variants.
- Lists — ordered, unordered (`-`/`*`/`+`), nested.
- Inline code (single, double, or N backticks).
- Indented code blocks (4-space) and fenced code blocks (see *Extended*).
- Horizontal rules (`***`, `---`, `___`).
- Escape sequences (`\X` for any punctuation).
- Inline links `[text](url)` — clickable; external URLs open in a new tab, in-vault links navigate via the SPA router.
- Link titles `[text](url "hover")` — surfaced as the `title=` attribute (browser tooltip).
- Autolinks for URLs and emails (`<https://...>`, `<a@b.c>`).
- Bold/italic/code wrapping a link.
- Reference-style links: full form `[text][label]` + `[label]: url "title"`, and the shortcut form `[label]` + `[label]: url`. Labels match case-insensitively, with whitespace trimmed.
- Images `![alt](src)` — vault-relative paths resolve against the containing note's directory; absolute and external URLs pass through unchanged. Empty alt (`![](src)`) is fully supported, standalone or inline mid-sentence.
- Image titles `![alt](src "hover")` — `<img title="...">`.

**Missing**

- Linked image `[![alt](src)](url)` — image renders; the wrapping link doesn't get a separate decoration.

**Out of scope (will not be added)**

- Inline HTML (`<em>word</em>`, `<br>`, etc.). Block HTML works via ixora's `htmlBlock` styling, but inline HTML inside paragraphs is not surfaced.

### Extended syntax

Reference: [markdownguide.org/extended-syntax](https://www.markdownguide.org/extended-syntax/).

**Supported**

- Tables — rendered as a CSS-grid widget per row when the cursor is elsewhere; the row containing the cursor falls back to raw `| col | col |` markdown for editing. Header row is `surface0` background + lavender bold + slightly larger font; separator row collapses to a thin accent stripe but stays arrow-navigable.
- Table cell formatting — bold/italic/inline-code/strikethrough/escape inside cells, driven by the lezer-markdown parser (no regex), so the GFM rules for intra-word underscores etc. are honored.
- Fenced code blocks (` ``` ` and ` ~~~ `).
- Syntax highlighting in fenced code blocks — `@codemirror/language-data` lazily loads per-language packs (~50 languages: JS, TS, Python, Rust, Go, JSON, HTML, CSS, SQL, YAML, Bash, Java, C/C++, PHP, Ruby, and more) and the `catppuccinHighlight` style colors the tokens.
- Strikethrough (`~~text~~`).
- Task lists (`- [x]` / `- [ ]`).
- Automatic URL linking (autolink extension).
- Disabling auto-link by wrapping in backticks (`` `https://x.com` ``).
- Highlight (`==text==`) — custom inline extension (`lib/md-highlight.ts`, mirrors lezer's Strikethrough rules: exactly two `=`, emphasis-style flanking); renders with a translucent yellow background, marks hidden cursor-aware.
- Subscript (`H~2~O`) — `@lezer/markdown`'s `Subscript` extension; rendered via `vertical-align: sub`, marks hidden cursor-aware.
- Superscript (`X^2^`) — `@lezer/markdown`'s `Superscript` extension; rendered via `vertical-align: super`, marks hidden cursor-aware.
- Emoji shortcodes (`:joy:`, `:t-rex:`, `:+1:`) — custom parser (`lib/md-emoji.ts`; lezer's stock `Emoji` misses hyphens/signs, so `:t-rex:` and `:+1:` wouldn't parse); the gemoji dataset (GitHub's ~1900 names, lazy-loaded like the code-block language packs) resolves known names to glyphs at render time, cursor-aware. Unknown shortcodes stay raw text; the file always keeps the literal `:shortcode:`. `Cmd/Ctrl-E` opens a picker that inserts one at the cursor.

**Missing — candidates for follow-up**

- Table alignment (`:---`, `:---:`, `---:`) — separator colons aren't parsed; cells default to left-aligned.

- Footnotes (`[^1]` and `[^1]: text`) — no parser extension shipped with `@lezer/markdown`; would need a custom inline parser + a reference-style resolution pass.
- Heading IDs (`### Title {#custom-id}`) — would need both parsing and integration with the URL/anchor system.
- Definition lists (`Term\n: Def`) — no parser extension shipped; non-trivial render.

**Out of scope (will not be added)**

- In-buffer emoji autocompletion (a GitHub/Slack-style popup while typing `:smi…`). Deliberate: the `Cmd/Ctrl-E` picker exists precisely so the editor never interrupts typing with completion UI. Type the shortcode blind or use the picker.

### Project-specific syntax (beyond CommonMark/GFM)

**Supported**

- Wiki links — `[[target]]` and `[[target|alias]]`. Clickable; navigates intra-app via the SPA router (no full reload). Dashed-underline visual to distinguish from regular `[text](url)` links. The target is the doc-id form (no `.md` suffix, no leading `/`); resolution follows the backend's md-wins / asset-fallback rule.
- Wiki-link image embeds — `![[pic.png]]` and `![[pic.png|alt]]` (Obsidian's default embed syntax). The browser makes **one request** (`GET /api/embed?note=…&target=…`) and the server resolves the target at request time: **adjacent to the note first** (a folder next to the note overshadows a same-named one at the vault root), vault root second — two `stat()` calls, always fresh, no wasted 404 round-trip. `..` segments are allowed while the result stays inside the vault. No shortest-unique-path search beyond that: an Obsidian vault set to "New link format: Absolute path in vault" or "Relative to file" round-trips; the default "shortest path" resolves only when the bare name lives next to the note or at the root. Non-image targets (`![[note]]` transclusion) stay raw — out of scope.

## Editor

**Supported**

- Catppuccin Latte (light) and Mocha (dark) — auto-switch based on `prefers-color-scheme`.
- Live preview — markdown structure rendered inline while editing; the source line under the cursor falls back to raw markup for editing. Applies per-line for tables, headings, links, images, HR, wiki-links.
- Yjs CRDT sync — multi-client live collaboration via `y-websocket` and `y-codemirror.next`. The server holds the canonical Doc; clients exchange updates.
- Asset viewer — for files visited via the URL bar:
  - Images (`png`/`jpg`/`gif`/`svg`/`webp`/`avif`/`bmp`/`ico`) render natively inside the SPA chrome.
  - Video (`mp4`/`webm`/`mov`/`m4v`/`ogv`) — native `<video controls>`.
  - Audio (`mp3`/`wav`/`ogg`/`flac`/`m4a`/`aac`) — native `<audio controls>`.
  - Everything else (PDF, plain text, etc.) — iframe fallback to the browser's built-in viewer.
- Backend file-existence disambiguation — `.md` always wins. URL `/foo.jpg` resolves to `<vault>/foo.jpg.md` if it exists; otherwise to `<vault>/foo.jpg`.
- Upload dispatch by source file — `Cmd+U` opens the OS file picker first; if the source filename ends in `.md` it's stored as a markdown note (with the user's typed extension becoming part of the doc-id basename), otherwise it's stored as an asset at the literal target path.
- Editor options panel (`Cmd/Ctrl-Alt-O`) — checkboxes for four local, remembered preferences: **Vim mode** (optional `@replit/codemirror-vim` keymap, with a NORMAL/INSERT/VISUAL mode badge), **Show line numbers**, **Relative line numbers** (hybrid: absolute on the cursor line, distance elsewhere), and **Center current line** (typewriter scrolling — keeps the cursor line vertically centered, except near the top/bottom of the file where it clamps naturally). While the panel is open, `⌥V` / `⌥N` / `⌥R` / `⌥C` toggle the rows without the mouse. All off by default and persisted in `localStorage` (`mdshards:*`, see `frontend/src/lib/editor-prefs.ts`); changes also propagate live across open tabs via the `storage` event.

### Keyboard shortcuts (global)

| Shortcut | Action |
|---|---|
| `Cmd/Ctrl-K` | Quick switcher — open or create a note. |
| `Cmd/Ctrl-Shift-K` | Rename the current file (md or asset). |
| `Cmd/Ctrl-Backspace` | Delete-file picker — confirms before unlinking. |
| `Cmd/Ctrl-U` | Upload a file into the vault. |
| `Cmd/Ctrl-E` | Emoji picker — search by name/description, Enter inserts `:shortcode:` at the cursor (md notes only). |
| `Cmd/Ctrl-Alt-O` | Editor options panel — vim mode, line numbers, relative line numbers, center current line (all remembered locally). |
| `Enter` (inside quick switcher) | Open the highlighted existing note. Never creates — a no-op when nothing matches. |
| `Shift+Enter` (inside quick switcher) | Create a note at the typed text (the only way to create). Works whether or not matches are highlighted. |

Shortcuts work in the editor, in the asset viewer (re-bound inside the iframe's `contentDocument` for same-origin assets), and on the NotFound page.

### Out of scope (will not be added)

- **Per-cell table editing** — clicking inside a rendered cell drops the entire row's widget, not just the cell. True cell-level live preview would require cursor + widget coexistence per cell.

## Architecture & vault

See [CLAUDE.md](./CLAUDE.md) for the load-bearing architectural decisions —
CRDT-as-substrate, server-as-source-of-truth, plain-`.md` vault with no DB
or sidecars, file-existence-based URL routing, Sec-Fetch-Dest-driven
asset-vs-SPA-shell behavior, and the upload-forces-md rule.
