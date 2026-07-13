/**
 * Project-specific live-render rules that layer on top of @retronav/ixora.
 * Ixora handles the generic primitives (inline-mark hiding, list bullets +
 * task checkboxes, blockquote, code blocks, html blocks); this module covers
 * the four things our app needs differently:
 *
 *   1. Strict ATX heading context — only style `#` lines that are surrounded
 *      by blank lines (markdownguide.org/basic-syntax best practice).
 *   2. `---` / `***` / `___` rendered as a divider when the cursor is elsewhere.
 *   3. Inline links that resolve vault-relative URLs and open on click via a
 *      `EditorView.domEventHandlers` mousedown handler.
 *   4. Inline images that resolve vault-relative paths the same way.
 */

import { syntaxTree } from '@codemirror/language'
import { StateEffect } from '@codemirror/state'
import type { Range, Text } from '@codemirror/state'
import type { SyntaxNode, Tree } from '@lezer/common'
import {
  Decoration,
  type DecorationSet,
  EditorView,
  type PluginValue,
  ViewPlugin,
  type ViewUpdate,
  WidgetType,
} from '@codemirror/view'
import { backendUrl } from './backend'
import { getNameToEmoji, loadEmojiData } from './emoji'
import { parseWikilinkBody } from './wikilink'

// Inline emphasis / code marks are hidden by ixora's `hideMarks()` (its
// list is hardcoded to Emphasis/InlineCode/Strikethrough). We own HeaderMark
// hiding because the strict heading-context rule means we sometimes need to
// leave the `#` visible, and the extended-syntax marks (`==` highlight,
// `~` subscript, `^` superscript) because ixora doesn't know them. All hide
// cursor-aware: the raw markup reappears while the selection touches the
// parent node.
const MARK_NODE_NAMES = new Set([
  'HeaderMark',
  'HighlightMark',
  'SubscriptMark',
  'SuperscriptMark',
])

// Extended-syntax inline wrappers → the CSS class that renders them
// (style.css). Applied as a mark decoration over the whole node; the
// delimiter chars inside are hidden separately via MARK_NODE_NAMES.
const INLINE_CLASS_NODES: Record<string, string> = {
  Highlight: 'cm-md-mark',
  Subscript: 'cm-md-sub',
  Superscript: 'cm-md-sup',
}

// `:shortcode:` → glyph rendering for the Emoji extension, backed by the
// lazily-loaded gemoji dataset (lib/emoji.ts). Unknown shortcodes stay raw
// text; the cursor inside reveals the shortcode for editing, like every
// other piece of hidden markup. The FILE always keeps the literal
// `:shortcode:` — the glyph is render-time only.
class EmojiWidget extends WidgetType {
  glyph: string
  constructor(glyph: string) {
    super()
    this.glyph = glyph
  }
  override eq(other: EmojiWidget): boolean {
    return other.glyph === this.glyph
  }
  toDOM(): HTMLElement {
    const span = document.createElement('span')
    span.className = 'cm-md-emoji'
    span.textContent = this.glyph
    return span
  }
}

/** Fired into a view when the gemoji dataset finishes loading, so the
 *  markdownLive plugin rebuilds and the shortcodes that were left raw on the
 *  first pass get their glyphs. */
const emojiDataRefresh = StateEffect.define<null>()

// One pending refresh per view — several decoration passes can run before
// the (single, shared) dataset load resolves.
const pendingEmojiRefresh = new WeakSet<EditorView>()

function loadEmojiDataThenRefresh(view: EditorView): void {
  if (pendingEmojiRefresh.has(view)) return
  pendingEmojiRefresh.add(view)
  void loadEmojiData().then(() => {
    pendingEmojiRefresh.delete(view)
    try {
      view.dispatch({ effects: emojiDataRefresh.of(null) })
    } catch {
      // View was destroyed while the dataset loaded — nothing to refresh.
    }
  })
}

/** Resolve a vault-relative asset reference against the note's own directory.
 *  Assets are vault helpers — refs that don't land inside the vault must not
 *  retrieve. Pass-through is intentionally narrow:
 *
 *    - `http://` / `https://` — explicit external resource (FEATURES.md
 *      contract; the vault portability rule already forbids using these for
 *      in-vault assets, so a host-absolute ref is by definition external).
 *    - `data:` — inline bytes, no network fetch.
 *
 *  Anything else with a `scheme:` prefix (`file:`, `javascript:`, `ftp:`,
 *  ...) and protocol-relative `//host/...` (which a same-origin `/`-check
 *  would otherwise wave through to evil.com) are blocked by returning an
 *  empty string — the browser renders the image slot without a src.
 *
 *  Vault-relative refs (`foo.png`, `./foo.png`, `../foo.png`) are walked
 *  segment-by-segment against the note's directory. A `..` that would step
 *  above the vault root is *not* silently capped at `/` (the URL
 *  constructor would do that, which would let `../foo.png` from `index`
 *  silently render `<vault>/foo.png`); instead we treat the ref as
 *  out-of-vault and return `''`, mirroring the user's mental model that
 *  "../foo.png from the root means a file that doesn't exist in our
 *  universe." Refs that DO land inside the vault but point at a file the
 *  user hasn't created yet still return their `/path`; the backend 404s
 *  and the browser shows the usual broken-image icon — that's the "name
 *  predefined for a future upload, or a typo" case. */
export function resolveAssetUrl(noteDocId: string, ref: string): string {
  if (/^https?:\/\//i.test(ref)) return ref
  if (/^data:/i.test(ref)) return ref
  if (ref.startsWith('//')) return ''
  if (/^[a-z][a-z0-9+.-]*:/i.test(ref)) return ''
  if (ref.startsWith('/')) return ref
  // Walk segments. dirParts is the note's parent directory; `..` pops one
  // level, `.` and empty segments are skipped, anything else is appended.
  // Popping from an empty dir means the ref escapes the vault → ''.
  //
  // The note's own directory comes from the raw (decoded) doc-id, so its
  // segments must be percent-encoded to be fetchable. The ref's segments are
  // authored as a URL already — spaces are written `%20` (or angle-bracketed,
  // which the parser rejects otherwise) — so they pass through untouched.
  // Re-encoding them would turn `%20` into `%2520`.
  const dirParts = noteDocId
    .split('/')
    .slice(0, -1)
    .filter((p) => p !== '')
    .map(encodeURIComponent)
  for (const seg of ref.split('/')) {
    if (seg === '' || seg === '.') continue
    if (seg === '..') {
      if (dirParts.length === 0) return ''
      dirParts.pop()
      continue
    }
    dirParts.push(seg)
  }
  return '/' + dirParts.join('/')
}

class ImageWidget extends WidgetType {
  readonly alt: string
  readonly src: string
  readonly title: string | null
  constructor(alt: string, src: string, title: string | null = null) {
    super()
    this.alt = alt
    this.src = src
    this.title = title
  }
  eq(other: ImageWidget): boolean {
    return other.alt === this.alt && other.src === this.src && other.title === this.title
  }
  toDOM(): HTMLElement {
    if (!this.src) {
      // resolveAssetUrl rejected this ref (vault escape, blocked scheme,
      // or protocol-relative). Render a labeled placeholder span instead
      // of an `<img>` — `<img>` is a replaced element, so CSS can't draw
      // the alt text on it. A span with role="img" stays semantically an
      // image while leaving the alt text visible to the user.
      const span = document.createElement('span')
      span.className = 'cm-md-image cm-md-image-missing'
      span.setAttribute('role', 'img')
      span.setAttribute('aria-label', this.alt)
      span.textContent = this.alt
      if (this.title !== null) span.title = this.title
      return span
    }
    const img = document.createElement('img')
    img.alt = this.alt
    img.src = this.src
    if (this.title !== null) img.title = this.title
    img.className = 'cm-md-image'
    return img
  }
  ignoreEvent(): boolean {
    return false
  }
}

/** Strip the surrounding quotes (`"…"`, `'…'`, `(…)`) from a `LinkTitle`
 *  node's source text. lezer-markdown captures the title *with* its
 *  delimiters; we want just the content. */
function unwrapLinkTitle(raw: string): string {
  if (raw.length < 2) return raw
  const first = raw[0]
  const last = raw.at(-1)
  const ok =
    (first === '"' && last === '"') ||
    (first === "'" && last === "'") ||
    (first === '(' && last === ')')
  return ok ? raw.slice(1, -1) : raw
}

interface LinkRef {
  url: string
  title?: string
}

/** Walk the tree once before the main pass to harvest every
 *  `LinkReference` definition (`[label]: url "title"`). The key is the
 *  lowercase, whitespace-trimmed label — CommonMark says reference labels
 *  match case-insensitively. */
function collectLinkRefs(tree: Tree, doc: Text): Map<string, LinkRef> {
  const refs = new Map<string, LinkRef>()
  tree.iterate({
    enter: (node) => {
      if (node.name !== 'LinkReference') return undefined
      let label: string | null = null
      let url = ''
      let title: string | undefined
      for (let c = node.node.firstChild; c; c = c.nextSibling) {
        if (c.name === 'LinkLabel') {
          const raw = doc.sliceString(c.from, c.to)
          label = raw.slice(1, -1).trim().toLowerCase()
        } else if (c.name === 'URL') {
          url = doc.sliceString(c.from, c.to)
        } else if (c.name === 'LinkTitle') {
          title = unwrapLinkTitle(doc.sliceString(c.from, c.to))
        }
      }
      if (label !== null && url) refs.set(label, title ? { url, title } : { url })
      return false
    },
  })
  return refs
}

/**
 * Widget that renders a markdown table row as a real CSS grid of cells. We
 * replace the entire line text with one of these so the `.cm-line` itself
 * stays `display: block` — CodeMirror's vertical-motion logic needs that to
 * compute y-positions for ArrowUp/Down between lines. The grid lives inside
 * the widget (one level deeper), out of CM's way.
 */
/** A single inline run inside a table cell. lezer-markdown already parsed
 *  the structure — `parseCellRuns` just walks its tree and emits this
 *  representation, which the widget converts to DOM. No regex needed; all
 *  the GFM rules (word-boundary underscores, lazy matching, escape) come
 *  from the parser. */
type CellRun =
  | { k: 'text'; text: string }
  | { k: 'code'; text: string }
  | { k: 'bold'; runs: CellRun[] }
  | { k: 'italic'; runs: CellRun[] }
  | { k: 'strike'; runs: CellRun[] }

/** Walk `parent`'s children within `[from, to)` and emit a flat list of
 *  CellRuns. Marker nodes (`EmphasisMark`, `CodeMark`, `StrikethroughMark`)
 *  contribute nothing — they're the `**`/`*`/``/`~~` delimiters. Wrapper
 *  nodes recurse so nested emphasis works. Implicit text (the gaps between
 *  explicit nodes) is emitted as plain `text` runs. */
function parseInlineRuns(from: number, to: number, parent: SyntaxNode, doc: Text): CellRun[] {
  const runs: CellRun[] = []
  let cursor = from
  for (let child = parent.firstChild; child; child = child.nextSibling) {
    if (child.to <= from || child.from >= to) continue
    // Markers — skip the source chars without emitting any run.
    if (
      child.name === 'EmphasisMark' ||
      child.name === 'CodeMark' ||
      child.name === 'StrikethroughMark' ||
      child.name === 'LinkMark'
    ) {
      if (child.from > cursor) {
        runs.push({ k: 'text', text: doc.sliceString(cursor, child.from) })
      }
      cursor = child.to
      continue
    }
    if (child.from > cursor) {
      runs.push({ k: 'text', text: doc.sliceString(cursor, child.from) })
    }
    switch (child.name) {
      case 'StrongEmphasis':
        runs.push({ k: 'bold', runs: parseInlineRuns(child.from, child.to, child, doc) })
        break
      case 'Emphasis':
        runs.push({ k: 'italic', runs: parseInlineRuns(child.from, child.to, child, doc) })
        break
      case 'Strikethrough':
        runs.push({ k: 'strike', runs: parseInlineRuns(child.from, child.to, child, doc) })
        break
      case 'InlineCode': {
        // Code spans have CodeMark children at the boundaries; the text
        // between them is what we want.
        let textFrom = child.from
        let textTo = child.to
        for (let m = child.firstChild; m; m = m.nextSibling) {
          if (m.name === 'CodeMark') {
            if (m.from === child.from) textFrom = m.to
            if (m.to === child.to) textTo = m.from
          }
        }
        runs.push({ k: 'code', text: doc.sliceString(textFrom, textTo) })
        break
      }
      case 'Escape':
        // `\X` — drop the backslash, keep the escaped character.
        runs.push({ k: 'text', text: doc.sliceString(child.from + 1, child.to) })
        break
      default:
        // Anything we don't handle (Link, Image, etc.) — emit the raw text
        // and don't descend. Tighten later as needed.
        runs.push({ k: 'text', text: doc.sliceString(child.from, child.to) })
        break
    }
    cursor = child.to
  }
  if (cursor < to) {
    runs.push({ k: 'text', text: doc.sliceString(cursor, to) })
  }
  return runs
}

/** Render a flat CellRun list into a DOM fragment. */
function runsToDom(runs: readonly CellRun[]): DocumentFragment {
  const frag = document.createDocumentFragment()
  for (const run of runs) {
    switch (run.k) {
      case 'text':
        frag.appendChild(document.createTextNode(run.text))
        break
      case 'code': {
        const code = document.createElement('code')
        code.textContent = run.text
        frag.appendChild(code)
        break
      }
      case 'bold': {
        const strong = document.createElement('strong')
        strong.appendChild(runsToDom(run.runs))
        frag.appendChild(strong)
        break
      }
      case 'italic': {
        const em = document.createElement('em')
        em.appendChild(runsToDom(run.runs))
        frag.appendChild(em)
        break
      }
      case 'strike': {
        const del = document.createElement('del')
        del.appendChild(runsToDom(run.runs))
        frag.appendChild(del)
        break
      }
    }
  }
  return frag
}

/**
 * Widget that renders a markdown table row as a real CSS grid of cells. We
 * replace the entire line text with one of these so the `.cm-line` itself
 * stays `display: block` — CodeMirror's vertical-motion logic needs that to
 * compute y-positions for ArrowUp/Down between lines. The grid lives inside
 * the widget (one level deeper), out of CM's way.
 *
 * Cell contents are passed in as pre-parsed `CellRun[]` (built from the
 * lezer-markdown tree in `buildDecorations`) so the widget never re-parses
 * markdown — `toDOM` is just a DOM serialiser.
 */
class TableRowWidget extends WidgetType {
  readonly cells: readonly CellRun[][]
  readonly kind: 'header' | 'data' | 'separator'
  /** Stable identity computed from `cells` so `eq` is a cheap string compare
   *  instead of a deep walk. The renderer never mutates the runs after
   *  construction. */
  private readonly key: string
  constructor(cells: readonly CellRun[][], kind: 'header' | 'data' | 'separator') {
    super()
    this.cells = cells
    this.kind = kind
    this.key = JSON.stringify(cells)
  }
  eq(other: TableRowWidget): boolean {
    return other.kind === this.kind && other.key === this.key
  }
  toDOM(): HTMLElement {
    const row = document.createElement('div')
    let baseClass = 'cm-md-table-row'
    if (this.kind === 'header') baseClass = 'cm-md-table-row cm-md-table-header'
    else if (this.kind === 'separator') baseClass = 'cm-md-table-separator'
    row.className = baseClass
    if (this.kind !== 'separator') {
      row.style.setProperty('--cm-md-table-cols', `repeat(${this.cells.length}, 1fr)`)
      for (const runs of this.cells) {
        const cell = document.createElement('span')
        cell.className = 'cm-md-table-cell'
        cell.appendChild(runsToDom(runs))
        row.appendChild(cell)
      }
    }
    return row
  }
  ignoreEvent(): boolean {
    return false
  }
}

function rangesOverlap(a0: number, a1: number, b0: number, b1: number): boolean {
  return a0 <= b1 && b0 <= a1
}

interface BuildOpts {
  noteDocId: string
  /** Called when the user clicks a wiki link `[[target]]`. The target is the
   *  raw doc-id from inside the brackets (no leading slash). */
  onNavigate: (target: string) => void
}

const HEADING_NAME_RE = /^ATXHeading([1-6])$/
const SETEXT_NAME_RE = /^SetextHeading([12])$/

/**
 * Per the Markdown Guide (markdownguide.org/basic-syntax) best practice, an
 * ATX heading should be separated by blank lines from surrounding content.
 * lezer-markdown follows CommonMark and parses `#`-prefixed lines as headings
 * regardless of context, so we gate the visual heading treatment ourselves:
 * only render as a heading when the previous and next lines are blank (or the
 * heading is at the document edge).
 *
 * Returns true if the heading should be styled, false if the `#` should be
 * left as plain text.
 */
export function isValidAtxHeading(
  prevLine: string | null,
  nextLine: string | null,
): boolean {
  const prevOk = prevLine === null || prevLine.trim() === ''
  const nextOk = nextLine === null || nextLine.trim() === ''
  return prevOk && nextOk
}

interface BuiltDecorations {
  /** Everything that affects rendering — cells, pipes, marks, line classes,
   *  replacements. Fed to the plugin's `decorations` getter. */
  visual: DecorationSet
  /** A *subset* of `visual` containing only ranges the cursor should treat
   *  as atomic (skip over). Without this split, providing every decoration
   *  to `EditorView.atomicRanges` makes the whole rendered table one big
   *  atomic block — ArrowDown from the line above would jump past it. */
  atomic: DecorationSet
}

function buildDecorations(view: EditorView, opts: BuildOpts): BuiltDecorations {
  const ranges: Range<Decoration>[] = []
  const atomicRanges: Range<Decoration>[] = []
  const { from: selFrom, to: selTo } = view.state.selection.main
  const tree = syntaxTree(view.state)
  const doc = view.state.doc
  const linkRefs = collectLinkRefs(tree, doc)

  /** Push a decoration that should also be treated as atomic by the cursor —
   *  i.e. cursor movement skips its range. Use for Replace decorations that
   *  hide markup the user shouldn't be able to position inside (e.g. the
   *  `[` of a link, the `---` of a horizontal rule, an image widget). DO
   *  NOT use for Mark decorations whose content is still visible/editable
   *  (e.g. table cells, the wikilink label). */
  function pushAtomic(r: Range<Decoration>): void {
    ranges.push(r)
    atomicRanges.push(r)
  }

  const visited = new Set<number>()
  // ATX headings whose surrounding lines disqualify them from being rendered
  // as headings — used to suppress the `#`-marker hiding below so the line
  // stays as raw text.
  const ignoredHeadings = new Set<number>()

  tree.iterate({
    enter: (node) => {
      // Headings: tag the line so CSS can size H1..H6 distinctly, but only
      // when the heading is properly surrounded by blank lines (or sits at
      // the edge of the document) — see `isValidAtxHeading`.
      const headingMatch = HEADING_NAME_RE.exec(node.name)
      if (headingMatch) {
        const line = doc.lineAt(node.from)
        const prev = line.number > 1 ? doc.line(line.number - 1).text : null
        const next = line.number < doc.lines ? doc.line(line.number + 1).text : null
        if (isValidAtxHeading(prev, next)) {
          const level = Number(headingMatch[1])
          ranges.push(Decoration.line({ class: `cm-md-h${level}` }).range(line.from))
        } else {
          ignoredHeadings.add(node.from)
        }
      }

      // Setext-style headings — `Heading 1\n=========` / `Heading 2\n---------`.
      // lezer-markdown emits SetextHeading1/2 spanning both lines, with a
      // HeaderMark child covering just the underline. Style the first line
      // (the text) the same as the ATX equivalent; the underline's
      // HeaderMark gets hidden by the MARK_NODE_NAMES branch below when the
      // cursor isn't on the heading.
      const setextMatch = SETEXT_NAME_RE.exec(node.name)
      if (setextMatch) {
        const line = doc.lineAt(node.from)
        const level = Number(setextMatch[1])
        ranges.push(Decoration.line({ class: `cm-md-h${level}` }).range(line.from))
      }

      // GFM table — each row's entire text content is replaced with a
      // `TableRowWidget` (a real DOM grid). The `.cm-line` itself stays in
      // CodeMirror's default `display: block`, which is the only shape its
      // vertical-motion math is happy with — that's why ArrowDown actually
      // navigates from line above the table through each row instead of
      // jumping over the whole block. The row with the cursor on it gets NO
      // decoration so the raw markdown source shows for editing.
      //
      // Tree shape (verified empirically):
      //   Table
      //     TableHeader       (the `| h | h |` row)
      //       TableDelimiter+ TableCell+
      //     TableDelimiter    (the `|---|---|` separator row, top-level)
      //     TableRow*         (each data row, same shape as TableHeader)
      if (node.name === 'Table') {
        for (let child = node.node.firstChild; child; child = child.nextSibling) {
          if (child.name === 'TableHeader' || child.name === 'TableRow') {
            const lineObj = doc.lineAt(child.from)
            if (rangesOverlap(lineObj.from, lineObj.to, selFrom, selTo)) continue
            // Walk the row's children once: collect pipe positions (used to
            // determine column count + locate empty cells) and TableCell
            // nodes keyed by start position. lezer-markdown only emits a
            // TableCell when there's content — empty cells like `| a |  |
            // c |` have no node — so we use the pipes to slot cells into
            // columns and fall back to an empty cell when no TableCell
            // sits between consecutive pipes. Also filter out rows with no
            // pipes (the parser's greedy spillover from pipe-less lines
            // attached to the table).
            const pipes: number[] = []
            const cellsByStart = new Map<number, SyntaxNode>()
            for (let g = child.firstChild; g; g = g.nextSibling) {
              if (g.name === 'TableDelimiter') pipes.push(g.from)
              else if (g.name === 'TableCell') cellsByStart.set(g.from, g.node)
            }
            if (pipes.length < 2) continue
            const cellRuns: CellRun[][] = []
            for (let i = 0; i < pipes.length - 1; i++) {
              const segmentFrom = pipes[i] + 1
              const segmentTo = pipes[i + 1]
              // Find the TableCell node whose range lies between this pair
              // of pipes, if any.
              let cell: SyntaxNode | null = null
              for (const [start, n] of cellsByStart) {
                if (start >= segmentFrom && start < segmentTo) {
                  cell = n
                  break
                }
              }
              cellRuns.push(
                cell ? parseInlineRuns(cell.from, cell.to, cell, doc) : [],
              )
            }
            pushAtomic(
              Decoration.replace({
                widget: new TableRowWidget(
                  cellRuns,
                  child.name === 'TableHeader' ? 'header' : 'data',
                ),
              }).range(lineObj.from, lineObj.to),
            )
          } else if (child.name === 'TableDelimiter') {
            // Top-level inside Table = the `|---|---|` separator row.
            const lineObj = doc.lineAt(child.from)
            if (rangesOverlap(lineObj.from, lineObj.to, selFrom, selTo)) continue
            pushAtomic(
              Decoration.replace({
                widget: new TableRowWidget([], 'separator'),
              }).range(lineObj.from, lineObj.to),
            )
          }
        }

        // Return false — there's nothing useful to do inside the table for
        // any other inline handler. Cell content gets rendered by the widget
        // directly from the source slice, so we don't need iterate to descend
        // and re-decorate Escape/Emphasis/Link inside cells. (Inline
        // formatting inside rendered cells is therefore plain text for now —
        // an explicit trade-off until the widget itself parses inline marks.)
        return false
      }

      // Backslash escapes (`\|`, `\*`, ...) — lezer-markdown emits an Escape
      // node spanning the two-character sequence. Hide just the leading `\`
      // when the cursor isn't on it, so the rendered text shows the literal
      // escaped character (`|`, `*`, ...). Mark + CSS `display: none` rather
      // than Replace, so we don't get the widgetBuffer noise that breaks the
      // table grid.
      if (node.name === 'Escape') {
        if (!rangesOverlap(node.from, node.to, selFrom, selTo)) {
          ranges.push(
            Decoration.mark({ class: 'cm-md-escape-mark' }).range(node.from, node.from + 1),
          )
        }
      }

      // Horizontal rule: when the cursor is elsewhere, swap the `---` /
      // `***` / `___` literal for a visual divider; otherwise show the raw
      // markup so it can be edited.
      if (node.name === 'HorizontalRule') {
        if (!rangesOverlap(node.from, node.to, selFrom, selTo)) {
          const lineStart = doc.lineAt(node.from).from
          ranges.push(Decoration.line({ class: 'cm-md-hr' }).range(lineStart))
          pushAtomic(Decoration.replace({}).range(node.from, node.to))
          visited.add(node.from)
          return false
        }
      }

      // Inline link `[label](url "title")` AND reference link `[label][id]` /
      // shortcut `[label]`. For inline, lezer emits a URL child (and
      // optionally a LinkTitle child); for reference forms there's no URL,
      // and we resolve it against the `LinkReference` definitions
      // pre-collected at the top of buildDecorations. Either way, hide the
      // brackets + URL portion and mark the visible label as clickable, with
      // an optional `title` attribute exposed as the hover tooltip.
      if (node.name === 'Link') {
        if (!rangesOverlap(node.from, node.to, selFrom, selTo)) {
          let closeBracket = -1
          let url = ''
          let title: string | null = null
          let labelText: string | null = null
          for (let child = node.node.firstChild; child; child = child.nextSibling) {
            if (
              child.name === 'LinkMark' &&
              doc.sliceString(child.from, child.to) === ']' &&
              closeBracket === -1
            ) {
              closeBracket = child.from
            }
            if (child.name === 'URL') {
              url = doc.sliceString(child.from, child.to)
            }
            if (child.name === 'LinkTitle') {
              title = unwrapLinkTitle(doc.sliceString(child.from, child.to))
            }
            if (child.name === 'LinkLabel') {
              const raw = doc.sliceString(child.from, child.to)
              labelText = raw.slice(1, -1).trim().toLowerCase()
            }
          }
          if (closeBracket > node.from + 1) {
            // Reference forms: no URL child — look up by explicit label or,
            // for the shortcut `[label]` form, by the bracketed text itself.
            if (!url) {
              const key =
                labelText ??
                doc.sliceString(node.from + 1, closeBracket).trim().toLowerCase()
              const ref = linkRefs.get(key)
              if (ref) {
                url = ref.url
                if (title === null && ref.title !== undefined) title = ref.title
              }
            }
            if (url) {
              const attrs: Record<string, string> = { 'data-href': url }
              if (title !== null) attrs.title = title
              pushAtomic(Decoration.replace({}).range(node.from, node.from + 1))
              ranges.push(
                Decoration.mark({
                  class: 'cm-md-link',
                  attributes: attrs,
                }).range(node.from + 1, closeBracket),
              )
              pushAtomic(Decoration.replace({}).range(closeBracket, node.to))
              visited.add(node.from)
              return false
            }
            // Unresolved reference (no matching definition) — leave the raw
            // markup visible so the user sees something's wrong.
          }
        }
      }

      // Wiki link `[[target]]` / `[[target|alias]]`: hide the brackets (and
      // the separator + target when an alias is present) and decorate the
      // visible label as clickable. Intra-app navigation happens via the
      // mousedown handler at the bottom of this file.
      if (node.name === 'Wikilink') {
        if (!rangesOverlap(node.from, node.to, selFrom, selTo)) {
          const inner = doc.sliceString(node.from + 2, node.to - 2)
          const parsed = parseWikilinkBody(inner)
          if (parsed) {
            const labelFrom = parsed.alias === null
              ? node.from + 2
              : node.from + 2 + parsed.target.length + 1 // past `target|`
            pushAtomic(Decoration.replace({}).range(node.from, labelFrom))
            ranges.push(
              Decoration.mark({
                class: 'cm-md-wikilink',
                attributes: { 'data-target': parsed.target },
              }).range(labelFrom, node.to - 2),
            )
            pushAtomic(Decoration.replace({}).range(node.to - 2, node.to))
            visited.add(node.from)
            return false
          }
        }
      }

      // Image `![alt](url "title")`: replace the whole node with the widget
      // when the cursor is outside. Walk the tree for URL + optional
      // LinkTitle — the alt text is the source between `![` and the first
      // closing `]`.
      if (node.name === 'Image') {
        if (!rangesOverlap(node.from, node.to, selFrom, selTo)) {
          let urlRaw = ''
          let title: string | null = null
          let closeBracket = -1
          for (let child = node.node.firstChild; child; child = child.nextSibling) {
            if (
              child.name === 'LinkMark' &&
              doc.sliceString(child.from, child.to) === ']' &&
              closeBracket === -1
            ) {
              closeBracket = child.from
            }
            if (child.name === 'URL') urlRaw = doc.sliceString(child.from, child.to)
            if (child.name === 'LinkTitle')
              title = unwrapLinkTitle(doc.sliceString(child.from, child.to))
          }
          if (urlRaw && closeBracket > node.from + 2) {
            const alt = doc.sliceString(node.from + 2, closeBracket)
            // In-vault refs resolve to origin-rooted paths; prefix the baked
            // backend origin when one is configured (deployment mode 3). The
            // FILE keeps its vault-relative ref — this is render-time only.
            const resolved = resolveAssetUrl(opts.noteDocId, urlRaw)
            const src =
              resolved && !/^(https?:|data:)/i.test(resolved) ? backendUrl(resolved) : resolved
            pushAtomic(
              Decoration.replace({ widget: new ImageWidget(alt, src, title) }).range(
                node.from,
                node.to,
              ),
            )
            visited.add(node.from)
            return false
          }
        }
      }
      const inlineClass = INLINE_CLASS_NODES[node.name]
      if (inlineClass) {
        ranges.push(Decoration.mark({ class: inlineClass }).range(node.from, node.to))
      }
      // Replace a known `:shortcode:` with its glyph when the cursor is
      // elsewhere. "Elsewhere" follows the same touching convention as the
      // Cmd-E token scanner (lib/emoji.ts::shortcodeTokenAt): the raw
      // shortcode shows from `|:smile:` through `:smile|:`, while `:smile:|`
      // — cursor just past the closed token — keeps the glyph. That boundary
      // also makes the emoji snap in the moment the closing `:` is typed.
      // Until the gemoji dataset arrives the shortcode stays raw; the load's
      // completion effect triggers a rebuild.
      const touchesEmoji = selFrom < node.to && selTo >= node.from
      if (node.name === 'Emoji' && !touchesEmoji) {
        const map = getNameToEmoji()
        if (!map) {
          loadEmojiDataThenRefresh(view)
          return
        }
        const glyph = map[doc.sliceString(node.from + 1, node.to - 1)]
        if (glyph) {
          // Deliberately NOT atomic: cursor movement is character-wise, so
          // ArrowLeft from `:smile:|` steps INSIDE to `:smile|:` (the move
          // makes the token "touched", the rebuild reveals it raw) instead
          // of leaping the whole token — which stranded the cursor at
          // `|:emoji1:` when two shortcodes sat back to back. The moment the
          // cursor lands in the range the widget is gone, so the usual
          // "cursor inside a replaced range" pitfalls don't apply.
          ranges.push(
            Decoration.replace({ widget: new EmojiWidget(glyph) }).range(node.from, node.to),
          )
        }
      }
      if (MARK_NODE_NAMES.has(node.name)) {
        const parent = node.node.parent
        if (!parent) return
        if (visited.has(parent.from)) return
        if (rangesOverlap(parent.from, parent.to, selFrom, selTo)) return
        // The parent ATXHeading didn't pass the blank-line check, so leave
        // the `#` visible as plain text instead of hiding it.
        if (node.name === 'HeaderMark' && ignoredHeadings.has(parent.from)) return
        // For `#` HeaderMarks, also swallow the one trailing space so the
        // heading text aligns with surrounding lines when the markup is hidden.
        let to = node.to
        if (node.name === 'HeaderMark' && doc.sliceString(to, to + 1) === ' ') {
          to += 1
        }
        pushAtomic(Decoration.replace({}).range(node.from, to))
      }
    },
  })

  return {
    visual: Decoration.set(ranges, true),
    atomic: Decoration.set(atomicRanges, true),
  }
}

function makeClickHandler(onNavigate: (target: string) => void) {
  return EditorView.domEventHandlers({
    mousedown(event) {
      const target = event.target as HTMLElement | null
      if (!target) return false
      // Wiki link first — intra-app navigation, no new tab.
      const wikiEl = target.closest('.cm-md-wikilink') as HTMLElement | null
      if (wikiEl) {
        const t = wikiEl.dataset.target
        if (!t) return false
        event.preventDefault()
        event.stopPropagation()
        onNavigate(t)
        return true
      }
      // Regular `[label](url)` — open in a new tab so external/asset links
      // don't blow away the current note.
      const linkEl = target.closest('.cm-md-link') as HTMLElement | null
      if (!linkEl) return false
      const href = linkEl.dataset.href
      if (!href) return false
      event.preventDefault()
      event.stopPropagation()
      window.open(href, '_blank', 'noopener,noreferrer')
      return true
    },
  })
}

export function markdownLive(opts: BuildOpts) {
  const plugin = ViewPlugin.fromClass(
    class implements PluginValue {
      decorations: DecorationSet
      atomic: DecorationSet
      constructor(view: EditorView) {
        const built = buildDecorations(view, opts)
        this.decorations = built.visual
        this.atomic = built.atomic
      }
      update(update: ViewUpdate) {
        if (
          update.docChanged ||
          update.selectionSet ||
          update.viewportChanged ||
          // The gemoji dataset finished loading — rebuild so shortcodes left
          // raw on the first pass get their glyphs.
          update.transactions.some((tr) => tr.effects.some((e) => e.is(emojiDataRefresh)))
        ) {
          const built = buildDecorations(update.view, opts)
          this.decorations = built.visual
          this.atomic = built.atomic
        }
      }
    },
    {
      decorations: (v) => v.decorations,
      provide: (p) =>
        EditorView.atomicRanges.of((view) => view.plugin(p)?.atomic ?? Decoration.none),
    },
  )
  return [plugin, makeClickHandler(opts.onNavigate)]
}
