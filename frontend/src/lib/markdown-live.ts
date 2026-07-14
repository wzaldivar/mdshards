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
import type { SyntaxNode, SyntaxNodeRef, Tree } from '@lezer/common'
import {
  Decoration,
  type DecorationSet,
  EditorView,
  type PluginValue,
  ViewPlugin,
  type ViewUpdate,
  WidgetType,
} from '@codemirror/view'
import { kindFor } from './asset-kind'
import { backendUrl } from './backend'
import { getNameToEmoji, loadEmojiData } from './emoji'
import { parseWikilink, parseWikilinkBody } from './wikilink'

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
// Marker nodes contribute no run — they're the `**`/`*`/`` ` ``/`~~`/`[` `]`
// delimiters, whose source chars are skipped.
const INLINE_MARKER_NAMES = new Set(['EmphasisMark', 'CodeMark', 'StrikethroughMark', 'LinkMark'])

/** Text of an InlineCode node between its boundary CodeMark delimiters. */
function inlineCodeText(node: SyntaxNode, doc: Text): string {
  let textFrom = node.from
  let textTo = node.to
  for (let m = node.firstChild; m; m = m.nextSibling) {
    if (m.name === 'CodeMark') {
      if (m.from === node.from) textFrom = m.to
      if (m.to === node.to) textTo = m.from
    }
  }
  return doc.sliceString(textFrom, textTo)
}

/** Build the run for a single non-marker child node. Wrapper nodes recurse. */
function childRun(child: SyntaxNode, doc: Text): CellRun {
  const inner = (): CellRun[] => parseInlineRuns(child.from, child.to, child, doc)
  if (child.name === 'StrongEmphasis') return { k: 'bold', runs: inner() }
  if (child.name === 'Emphasis') return { k: 'italic', runs: inner() }
  if (child.name === 'Strikethrough') return { k: 'strike', runs: inner() }
  if (child.name === 'InlineCode') return { k: 'code', text: inlineCodeText(child, doc) }
  // `\X` — drop the backslash, keep the escaped character.
  if (child.name === 'Escape') return { k: 'text', text: doc.sliceString(child.from + 1, child.to) }
  // Anything we don't handle (Link, Image, etc.) — emit the raw text.
  return { k: 'text', text: doc.sliceString(child.from, child.to) }
}

function parseInlineRuns(from: number, to: number, parent: SyntaxNode, doc: Text): CellRun[] {
  const runs: CellRun[] = []
  let cursor = from
  const emitGap = (until: number): void => {
    if (until > cursor) runs.push({ k: 'text', text: doc.sliceString(cursor, until) })
  }
  for (let child = parent.firstChild; child; child = child.nextSibling) {
    if (child.to <= from || child.from >= to) continue
    emitGap(child.from)
    if (!INLINE_MARKER_NAMES.has(child.name)) runs.push(childRun(child, doc))
    cursor = child.to
  }
  emitGap(to)
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

/** Shared accumulator + inputs threaded through the per-node `decorate*`
 *  handlers below. `buildDecorations` owns the arrays/sets; the handlers only
 *  push into them (visual decorations into `ranges`, atomic ones via
 *  `pushAtomic`) and read the selection / doc / resolved link refs. */
interface DecoContext {
  view: EditorView
  opts: BuildOpts
  doc: Text
  selFrom: number
  selTo: number
  linkRefs: Map<string, LinkRef>
  ranges: Range<Decoration>[]
  /** Nodes whose whole markup was replaced (HR, link, wikilink, image) so the
   *  MARK handler skips their now-hidden child marks. */
  visited: Set<number>
  /** ATX headings that failed the blank-line context check, so the `#`
   *  HeaderMark stays visible as plain text. */
  ignoredHeadings: Set<number>
  pushAtomic: (r: Range<Decoration>) => void
}

// Each handler below owns one node type from the live-preview matrix. They run
// in sequence per node (see `enter` in buildDecorations); node names are
// mutually exclusive, so at most one acts. A handler that fully renders its
// node — replacing the raw markup with a widget/hidden range — returns `true`
// to signal "stop descending into children"; the others return void.

/** ATX heading: tag the line so CSS sizes H1..H6, but only when the heading is
 *  properly surrounded by blank lines (or sits at a document edge) — see
 *  `isValidAtxHeading`. Otherwise remember it so the `#` marker stays raw. */
function decorateHeading(node: SyntaxNodeRef, ctx: DecoContext): void {
  const headingMatch = HEADING_NAME_RE.exec(node.name)
  if (!headingMatch) return
  const { doc } = ctx
  const line = doc.lineAt(node.from)
  const prev = line.number > 1 ? doc.line(line.number - 1).text : null
  const next = line.number < doc.lines ? doc.line(line.number + 1).text : null
  if (isValidAtxHeading(prev, next)) {
    const level = Number(headingMatch[1])
    ctx.ranges.push(Decoration.line({ class: `cm-md-h${level}` }).range(line.from))
  } else {
    ctx.ignoredHeadings.add(node.from)
  }
}

/** Setext heading (`Heading\n===` / `---`): style the text line like the ATX
 *  equivalent. The underline's HeaderMark is hidden by `decorateMark`. */
function decorateSetext(node: SyntaxNodeRef, ctx: DecoContext): void {
  const setextMatch = SETEXT_NAME_RE.exec(node.name)
  if (!setextMatch) return
  const line = ctx.doc.lineAt(node.from)
  const level = Number(setextMatch[1])
  ctx.ranges.push(Decoration.line({ class: `cm-md-h${level}` }).range(line.from))
}

/** Find the TableCell node whose start lies in `[from, to)`, if any.
 *  lezer-markdown omits a TableCell for empty cells, so a gap can be empty. */
function cellInSegment(
  cellsByStart: Map<number, SyntaxNode>,
  from: number,
  to: number,
): SyntaxNode | null {
  for (const [start, n] of cellsByStart) {
    if (start >= from && start < to) return n
  }
  return null
}

/** Slot a table row's inline content into columns using its pipe positions.
 *  Returns null for rows with fewer than two pipes (the parser's greedy
 *  spillover from pipe-less lines attached to the table). Empty cells fall
 *  back to an empty run list per gap. */
function tableRowCellRuns(child: SyntaxNode, doc: Text): CellRun[][] | null {
  const pipes: number[] = []
  const cellsByStart = new Map<number, SyntaxNode>()
  for (let g = child.firstChild; g; g = g.nextSibling) {
    if (g.name === 'TableDelimiter') pipes.push(g.from)
    else if (g.name === 'TableCell') cellsByStart.set(g.from, g.node)
  }
  if (pipes.length < 2) return null
  const cellRuns: CellRun[][] = []
  for (let i = 0; i < pipes.length - 1; i++) {
    const cell = cellInSegment(cellsByStart, pipes[i] + 1, pipes[i + 1])
    cellRuns.push(cell ? parseInlineRuns(cell.from, cell.to, cell, doc) : [])
  }
  return cellRuns
}

/** GFM table: replace each non-cursor row's text with a `TableRowWidget` (a
 *  real DOM grid). The `.cm-line` stays `display: block` so CodeMirror's
 *  vertical-motion math walks into each row; the row under the cursor gets no
 *  decoration so its raw markdown shows for editing.
 *
 *  Tree shape (verified empirically):
 *    Table
 *      TableHeader       (the `| h | h |` row)  →  TableDelimiter+ TableCell+
 *      TableDelimiter    (the `|---|---|` separator row, top-level)
 *      TableRow*         (each data row, same shape as TableHeader)
 *
 *  Returns true always: cell content is rendered by the widget straight from
 *  the source slice, so there's nothing for inline handlers to do inside — we
 *  stop iterate from descending. (Inline formatting inside rendered cells is
 *  therefore plain text — an explicit trade-off until the widget parses it.) */
/** Decorate one direct child of a Table node: a header/data row becomes a
 *  populated `TableRowWidget`, the top-level `|---|---|` becomes a separator
 *  widget. Anything else (or a row under the cursor) is left raw. */
function decorateTableChild(child: SyntaxNode, ctx: DecoContext): void {
  const isRow = child.name === 'TableHeader' || child.name === 'TableRow'
  if (!isRow && child.name !== 'TableDelimiter') return
  const { doc } = ctx
  const lineObj = doc.lineAt(child.from)
  if (rangesOverlap(lineObj.from, lineObj.to, ctx.selFrom, ctx.selTo)) return
  if (!isRow) {
    // Top-level inside Table = the `|---|---|` separator row.
    ctx.pushAtomic(
      Decoration.replace({ widget: new TableRowWidget([], 'separator') }).range(
        lineObj.from,
        lineObj.to,
      ),
    )
    return
  }
  const cellRuns = tableRowCellRuns(child, doc)
  if (!cellRuns) return
  ctx.pushAtomic(
    Decoration.replace({
      widget: new TableRowWidget(cellRuns, child.name === 'TableHeader' ? 'header' : 'data'),
    }).range(lineObj.from, lineObj.to),
  )
}

function decorateTable(node: SyntaxNodeRef, ctx: DecoContext): boolean {
  if (node.name !== 'Table') return false
  for (let child = node.node.firstChild; child; child = child.nextSibling) {
    decorateTableChild(child, ctx)
  }
  return true
}

/** Backslash escape (`\|`, `\*`, ...): hide just the leading `\` when the
 *  cursor isn't on it, so the rendered text shows the literal escaped char.
 *  Mark + `display: none` rather than Replace, to avoid the widgetBuffer noise
 *  that breaks the table grid. */
function decorateEscape(node: SyntaxNodeRef, ctx: DecoContext): void {
  if (node.name !== 'Escape') return
  if (rangesOverlap(node.from, node.to, ctx.selFrom, ctx.selTo)) return
  ctx.ranges.push(
    Decoration.mark({ class: 'cm-md-escape-mark' }).range(node.from, node.from + 1),
  )
}

/** Horizontal rule: swap the `---` / `***` / `___` for a visual divider when
 *  the cursor is elsewhere; otherwise show the raw markup for editing. */
function decorateHorizontalRule(node: SyntaxNodeRef, ctx: DecoContext): boolean {
  if (node.name !== 'HorizontalRule') return false
  if (rangesOverlap(node.from, node.to, ctx.selFrom, ctx.selTo)) return false
  const lineStart = ctx.doc.lineAt(node.from).from
  ctx.ranges.push(Decoration.line({ class: 'cm-md-hr' }).range(lineStart))
  ctx.pushAtomic(Decoration.replace({}).range(node.from, node.to))
  ctx.visited.add(node.from)
  return true
}

interface ParsedLinkParts {
  /** Offset of the first `]` LinkMark, or -1 if none. */
  closeBracket: number
  /** URL child text (empty for reference/shortcut forms). */
  url: string
  /** Unwrapped LinkTitle, or null. */
  title: string | null
  /** Lowercased bracket text of a LinkLabel child, or null. */
  labelText: string | null
}

/** Walk a Link/Image node's children once, pulling out the pieces both the
 *  link and image handlers need. Images never have a LinkLabel child, so
 *  `labelText` stays null there — harmless. */
function parseLinkChildren(node: SyntaxNode, doc: Text): ParsedLinkParts {
  let closeBracket = -1
  let url = ''
  let title: string | null = null
  let labelText: string | null = null
  for (let child = node.firstChild; child; child = child.nextSibling) {
    if (
      child.name === 'LinkMark' &&
      doc.sliceString(child.from, child.to) === ']' &&
      closeBracket === -1
    ) {
      closeBracket = child.from
    }
    if (child.name === 'URL') url = doc.sliceString(child.from, child.to)
    if (child.name === 'LinkTitle') {
      title = unwrapLinkTitle(doc.sliceString(child.from, child.to))
    }
    if (child.name === 'LinkLabel') {
      labelText = doc.sliceString(child.from, child.to).slice(1, -1).trim().toLowerCase()
    }
  }
  return { closeBracket, url, title, labelText }
}

/** Inline link `[label](url "title")` AND reference/shortcut forms
 *  `[label][id]` / `[label]`. For inline, lezer emits URL (+ optional
 *  LinkTitle); reference forms have no URL and resolve against the
 *  pre-collected `LinkReference` definitions. Either way, hide brackets + URL
 *  and mark the visible label clickable, with an optional hover `title`. */
function decorateLink(node: SyntaxNodeRef, ctx: DecoContext): boolean {
  if (node.name !== 'Link') return false
  const { doc, selFrom, selTo } = ctx
  if (rangesOverlap(node.from, node.to, selFrom, selTo)) return false
  const { closeBracket, url: parsedUrl, title: parsedTitle, labelText } = parseLinkChildren(
    node.node,
    doc,
  )
  let url = parsedUrl
  let title = parsedTitle
  if (closeBracket <= node.from + 1) return false
  // Reference forms: no URL child — look up by explicit label or, for the
  // shortcut `[label]` form, by the bracketed text itself.
  if (!url) {
    const key =
      labelText ?? doc.sliceString(node.from + 1, closeBracket).trim().toLowerCase()
    const ref = ctx.linkRefs.get(key)
    if (ref) {
      url = ref.url
      if (title === null && ref.title !== undefined) title = ref.title
    }
  }
  // Unresolved reference (no matching definition) — leave the raw markup
  // visible so the user sees something's wrong.
  if (!url) return false
  const attrs: Record<string, string> = { 'data-href': url }
  if (title !== null) attrs.title = title
  ctx.pushAtomic(Decoration.replace({}).range(node.from, node.from + 1))
  ctx.ranges.push(
    Decoration.mark({ class: 'cm-md-link', attributes: attrs }).range(
      node.from + 1,
      closeBracket,
    ),
  )
  ctx.pushAtomic(Decoration.replace({}).range(closeBracket, node.to))
  ctx.visited.add(node.from)
  return true
}

/** Wiki link `[[target]]` / `[[target|alias]]`: hide the brackets (and the
 *  separator + target when aliased) and mark the visible label clickable.
 *  Navigation happens via the mousedown handler. (`![[...]]` embeds never
 *  reach here — the stock Image parser wins the `!`; see `decorateImage`.) */
function decorateWikilink(node: SyntaxNodeRef, ctx: DecoContext): boolean {
  if (node.name !== 'Wikilink') return false
  const { doc, selFrom, selTo } = ctx
  if (rangesOverlap(node.from, node.to, selFrom, selTo)) return false
  const inner = doc.sliceString(node.from + 2, node.to - 2)
  const parsed = parseWikilinkBody(inner)
  if (!parsed) return false
  const labelFrom =
    parsed.alias === null
      ? node.from + 2
      : node.from + 2 + parsed.target.length + 1 // past `target|`
  ctx.pushAtomic(Decoration.replace({}).range(node.from, labelFrom))
  ctx.ranges.push(
    Decoration.mark({
      class: 'cm-md-wikilink',
      attributes: { 'data-target': parsed.target },
    }).range(labelFrom, node.to - 2),
  )
  ctx.pushAtomic(Decoration.replace({}).range(node.to - 2, node.to))
  ctx.visited.add(node.from)
  return true
}

/** Image `![alt](url "title")` and Obsidian embed `![[target]]` /
 *  `![[target|alt]]`: replace the whole node with an `ImageWidget` when the
 *  cursor is outside. Embeds resolve via `/api/embed` (one request,
 *  adjacent-to-note then vault root); non-image embed targets stay raw. */
function decorateImage(node: SyntaxNodeRef, ctx: DecoContext): boolean {
  if (node.name !== 'Image') return false
  const { doc, opts, selFrom, selTo } = ctx
  if (rangesOverlap(node.from, node.to, selFrom, selTo)) return false
  // The stock Image parser wins the `!` and yields an Image node with no URL
  // child whose text (past the bang) is `[[...]]` — detect it by shape.
  const embed = parseWikilink(doc.sliceString(node.from + 1, node.to))
  if (embed && kindFor(embed.target) === 'image') {
    const src = backendUrl(
      '/api/embed?note=' +
        encodeURIComponent(opts.noteDocId) +
        '&target=' +
        encodeURIComponent(embed.target),
    )
    ctx.pushAtomic(
      Decoration.replace({
        widget: new ImageWidget(embed.alias ?? embed.target, src, null),
      }).range(node.from, node.to),
    )
    ctx.visited.add(node.from)
    return true
  }
  const { closeBracket, url: urlRaw, title } = parseLinkChildren(node.node, doc)
  // `>=` : empty alt (`![](pic.png)`) is valid and common — Obsidian and
  // paste-from-clipboard both write it.
  if (!urlRaw || closeBracket < node.from + 2) return false
  const alt = doc.sliceString(node.from + 2, closeBracket)
  // In-vault refs resolve to origin-rooted paths; prefix the baked backend
  // origin when configured (deployment mode 3). The FILE keeps its
  // vault-relative ref — this is render-time only.
  const resolved = resolveAssetUrl(opts.noteDocId, urlRaw)
  const src =
    resolved && !/^(https?:|data:)/i.test(resolved) ? backendUrl(resolved) : resolved
  ctx.pushAtomic(
    Decoration.replace({ widget: new ImageWidget(alt, src, title) }).range(
      node.from,
      node.to,
    ),
  )
  ctx.visited.add(node.from)
  return true
}

/** Extended-syntax inline wrappers (highlight / sub / sup): mark the whole
 *  node with its CSS class. The delimiter chars are hidden by `decorateMark`,
 *  so this must NOT stop descent. */
function decorateInlineClass(node: SyntaxNodeRef, ctx: DecoContext): void {
  const inlineClass = INLINE_CLASS_NODES[node.name]
  if (!inlineClass) return
  ctx.ranges.push(Decoration.mark({ class: inlineClass }).range(node.from, node.to))
}

/** `:shortcode:` → glyph when the cursor is elsewhere. "Elsewhere" follows the
 *  Cmd-E touching convention: raw from `|:smile:` through `:smile|:`, glyph at
 *  `:smile:|`. Deliberately NOT atomic so cursor movement is character-wise.
 *  Until the gemoji dataset loads the shortcode stays raw; the load's
 *  completion effect triggers a rebuild. */
function decorateEmoji(node: SyntaxNodeRef, ctx: DecoContext): void {
  if (node.name !== 'Emoji') return
  const touchesEmoji = ctx.selFrom < node.to && ctx.selTo >= node.from
  if (touchesEmoji) return
  const map = getNameToEmoji()
  if (!map) {
    loadEmojiDataThenRefresh(ctx.view)
    return
  }
  const glyph = map[ctx.doc.sliceString(node.from + 1, node.to - 1)]
  if (glyph) {
    ctx.ranges.push(
      Decoration.replace({ widget: new EmojiWidget(glyph) }).range(node.from, node.to),
    )
  }
}

/** Inline/heading marks we own (HeaderMark + the extended-syntax delimiters):
 *  hide them via an atomic Replace when their parent isn't already fully
 *  replaced, isn't cursor-touched, and (for headings) passed the context
 *  check. `#` HeaderMarks also swallow one trailing space for alignment. */
function decorateMark(node: SyntaxNodeRef, ctx: DecoContext): void {
  if (!MARK_NODE_NAMES.has(node.name)) return
  const parent = node.node.parent
  if (!parent) return
  if (ctx.visited.has(parent.from)) return
  if (rangesOverlap(parent.from, parent.to, ctx.selFrom, ctx.selTo)) return
  if (node.name === 'HeaderMark' && ctx.ignoredHeadings.has(parent.from)) return
  let to = node.to
  if (node.name === 'HeaderMark' && ctx.doc.sliceString(to, to + 1) === ' ') {
    to += 1
  }
  ctx.pushAtomic(Decoration.replace({}).range(node.from, to))
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

  const ctx: DecoContext = {
    view,
    opts,
    doc,
    selFrom,
    selTo,
    linkRefs,
    ranges,
    visited,
    ignoredHeadings,
    pushAtomic,
  }

  // Node names are mutually exclusive, so these run in sequence and at most
  // one acts on a given node. A handler that fully renders its node returns
  // true → we stop iterate from descending into the now-hidden children.
  tree.iterate({
    enter: (node) => {
      decorateHeading(node, ctx)
      decorateSetext(node, ctx)
      if (decorateTable(node, ctx)) return false
      decorateEscape(node, ctx)
      if (decorateHorizontalRule(node, ctx)) return false
      if (decorateLink(node, ctx)) return false
      if (decorateWikilink(node, ctx)) return false
      if (decorateImage(node, ctx)) return false
      decorateInlineClass(node, ctx)
      decorateEmoji(node, ctx)
      decorateMark(node, ctx)
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
      // Root-absolute hrefs address the vault origin — route them through
      // backendUrl so a sub-path mount's prefix is applied. Relative hrefs
      // resolve against the current note URL, which already carries it.
      const openHref = href.startsWith('/') && !href.startsWith('//') ? backendUrl(href) : href
      window.open(openHref, '_blank', 'noopener,noreferrer')
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
