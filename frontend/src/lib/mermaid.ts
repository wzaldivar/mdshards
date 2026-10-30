/**
 * Live-preview rendering of ` ```mermaid ` fenced blocks as SVG diagrams.
 *
 * Lives beside `markdownLive` rather than inside it because CodeMirror only
 * accepts a replace decoration that spans line breaks from a `StateField` —
 * `markdownLive` is a `ViewPlugin`, which is why tables there render one
 * widget per row. A diagram has to replace the whole fence in one piece.
 *
 * Same cursor rule as every other widget: while the selection touches the
 * fence (including its boundaries) the raw source stays visible for editing.
 * Moving up/down into a diagram reveals it like a table or image: CodeMirror
 * moves vertically PAST a block widget, so `enterDiagram` stops an arrow press
 * that would skip one on the fence instead; `vimLineSteps` does the same
 * for vim's counted motions (`6j`), which must count the fence's source lines. The file always keeps the literal fence — the
 * diagram is render-time only, so the note round-trips through Obsidian.
 *
 * mermaid is bundled with the app (npm dependency, served from our own
 * `/_mdshards/assets/*` chunks — never a CDN) and dynamic-imported on the
 * first diagram so notes without one never pay for it.
 */

import { syntaxTree } from '@codemirror/language'
import { type EditorState, Prec, type Range, StateEffect, StateField } from '@codemirror/state'
import {
  Decoration,
  type DecorationSet,
  EditorView,
  keymap,
  ViewPlugin,
  type ViewUpdate,
  WidgetType,
} from '@codemirror/view'
import { getCM } from '@replit/codemirror-vim'
import DOMPurify from 'dompurify'

type Rendered = { ok: true; svg: string } | { ok: false; error: string }

/** Render results keyed by theme + source. Diagrams are rebuilt on every
 *  nearby edit (local or a remote CRDT splice), so re-running mermaid each
 *  time would flicker; identical source renders once. */
const cache = new Map<string, Rendered>()
const inflight = new Map<string, Promise<Rendered>>()
const CACHE_LIMIT = 200

type MermaidApi = typeof import('mermaid').default
let mermaidPromise: Promise<MermaidApi> | null = null
let initializedTheme: string | null = null
let renderSeq = 0

function loadMermaid(): Promise<MermaidApi> {
  mermaidPromise ??= import('mermaid').then((m) => m.default)
  return mermaidPromise
}

function isDark(): boolean {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
}

/** Catppuccin token (`"r, g, b"` triplet on :root) → `rgb(...)`. */
function ctp(name: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(`--ctp-${name}`).trim()
  return v ? `rgb(${v})` : ''
}

/** On a cold load the editor (and so the first diagram) can mount before
 *  the app stylesheet applies — WebKit does this — leaving every `--ctp-*`
 *  token empty, which mermaid rejects ("Unsupported color format").
 *  Wait a few frames for the palette to land before the first render. */
async function paletteReady(timeoutMs = 3000): Promise<boolean> {
  const deadline = performance.now() + timeoutMs
  while (!ctp('base')) {
    if (performance.now() > deadline) return false
    await new Promise((r) => requestAnimationFrame(r))
  }
  return true
}

function themeVariables(dark: boolean): Record<string, string | boolean> {
  const vars: Record<string, string> = {
    background: ctp('base'),
    primaryColor: ctp('surface0'),
    primaryBorderColor: ctp('lavender'),
    primaryTextColor: ctp('text'),
    secondaryColor: ctp('mantle'),
    tertiaryColor: ctp('crust'),
    lineColor: ctp('overlay2'),
    textColor: ctp('text'),
    mainBkg: ctp('surface0'),
    nodeBorder: ctp('lavender'),
    clusterBkg: ctp('mantle'),
    titleColor: ctp('lavender'),
    edgeLabelBackground: ctp('base'),
  }
  // A missing token falls back to mermaid's own default for that variable
  // rather than crashing the render.
  const set = Object.fromEntries(Object.entries(vars).filter(([, v]) => v))
  return { ...set, darkMode: dark, fontFamily: 'inherit' }
}

async function renderDiagram(source: string, key: string, dark: boolean): Promise<Rendered> {
  const id = `mdshards-mermaid-${++renderSeq}`
  let result: Rendered
  let themed = true
  // Everything — the chunk import and initialize() included — runs inside
  // the try: a throw that escapes leaves the widget on "Rendering…" forever.
  try {
    const [mermaid, ready] = await Promise.all([loadMermaid(), paletteReady()])
    themed = ready
    const theme = dark ? 'dark' : 'light'
    if (initializedTheme !== theme) {
      mermaid.initialize({
        startOnLoad: false,
        // Note text can come from any external writer (Syncthing/Obsidian) —
        // treat it as untrusted: no click bindings, no HTML in labels.
        securityLevel: 'strict',
        htmlLabels: false,
        theme: 'base',
        themeVariables: themeVariables(dark),
      })
      // An unthemed init is retried on the next render.
      initializedTheme = ready ? theme : null
    }
    const { svg } = await mermaid.render(id, source)
    result = {
      ok: true,
      svg: DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true } }),
    }
  } catch (e) {
    result = { ok: false, error: e instanceof Error ? e.message : String(e) }
    // mermaid leaves its scratch container behind on a parse error.
    document.getElementById(`d${id}`)?.remove()
  }
  // Don't pin an unthemed fallback render — the next rebuild retries it.
  if (themed) {
    if (cache.size >= CACHE_LIMIT) cache.delete(cache.keys().next().value!)
    cache.set(key, result)
  }
  return result
}

function cacheKey(source: string, dark: boolean): string {
  return `${dark ? 'd' : 'l'}\0${source}`
}

function getRendered(source: string, dark: boolean): Rendered | Promise<Rendered> {
  const key = cacheKey(source, dark)
  const hit = cache.get(key)
  if (hit) return hit
  let p = inflight.get(key)
  if (!p) {
    p = renderDiagram(source, key, dark).finally(() => inflight.delete(key))
    inflight.set(key, p)
  }
  return p
}

function fill(el: HTMLElement, r: Rendered): void {
  el.classList.remove('cm-md-mermaid-pending', 'cm-md-mermaid-error')
  if (r.ok) {
    el.innerHTML = r.svg
  } else {
    el.classList.add('cm-md-mermaid-error')
    el.textContent = `Mermaid: ${r.error}`
  }
}

class MermaidWidget extends WidgetType {
  readonly source: string
  readonly dark: boolean
  /** Whether the render was already cached when this widget was built. Part
   *  of `eq` so the post-render rebuild (see `diagramRendered`) swaps the
   *  placeholder DOM for a fresh one instead of reusing it. */
  readonly ready: boolean
  constructor(source: string, dark: boolean) {
    super()
    this.source = source
    this.dark = dark
    this.ready = cache.has(cacheKey(source, dark))
  }
  override eq(other: MermaidWidget): boolean {
    return other.source === this.source && other.dark === this.dark && other.ready === this.ready
  }
  toDOM(view: EditorView): HTMLElement {
    const el = document.createElement('div')
    el.className = 'cm-md-mermaid'
    const r = getRendered(this.source, this.dark)
    if (r instanceof Promise) {
      el.classList.add('cm-md-mermaid-pending')
      el.textContent = 'Rendering diagram…'
      void r.then((res) => {
        fill(el, res)
        // The block grew from the placeholder to the diagram under
        // CodeMirror, and a bare requestMeasure() doesn't re-measure content
        // heights (WebKit never did: the line-number gutter stayed offset by
        // the diagram's height). Rebuild the widget from the now-cached
        // render instead — a DOM swap through the normal update path always
        // re-measures. Skipped if this DOM was already replaced or the view
        // torn down meanwhile.
        if (el.isConnected) view.dispatch({ effects: diagramRendered.of(null) })
      })
    } else {
      fill(el, r)
    }
    // Click (or tap) a diagram to edit its source: move the cursor into the
    // fence, which flips the cursor rule and reveals the raw text.
    el.addEventListener('mousedown', (event) => {
      event.preventDefault()
      const line = view.state.doc.lineAt(view.posAtDOM(el))
      view.dispatch({ selection: { anchor: Math.min(line.to + 1, view.state.doc.length) } })
      view.focus()
    })
    return el
  }
  override get estimatedHeight(): number {
    return 200
  }
  override ignoreEvent(): boolean {
    return true
  }
}

/** Fires when the color scheme flips so diagrams re-render in the new theme. */
const themeChanged = StateEffect.define<null>()

/** Fires when an async render lands, so the field rebuilds the widget from
 *  the cache and CodeMirror re-measures its height (see `toDOM`). */
const diagramRendered = StateEffect.define<null>()

function buildMermaid(state: EditorState): DecorationSet {
  const ranges: Range<Decoration>[] = []
  const sel = state.selection.ranges
  const dark = isDark()
  syntaxTree(state).iterate({
    enter: (node) => {
      if (node.name !== 'FencedCode') return undefined
      const info = node.node.getChild('CodeInfo')
      if (!info || state.doc.sliceString(info.from, info.to).trim().toLowerCase() !== 'mermaid') {
        return false
      }
      // An unclosed fence runs to EOF and is still being typed — leave it raw.
      if (node.node.getChildren('CodeMark').length < 2) return false
      if (sel.some((r) => r.from <= node.to && r.to >= node.from)) return false
      const text = node.node.getChild('CodeText')
      const source = text ? state.doc.sliceString(text.from, text.to) : ''
      if (!source.trim()) return false
      const from = state.doc.lineAt(node.from).from
      const to = state.doc.lineAt(node.to).to
      ranges.push(
        Decoration.replace({ widget: new MermaidWidget(source, dark), block: true }).range(
          from,
          to,
        ),
      )
      return false
    },
  })
  return Decoration.set(ranges)
}

const mermaidField = StateField.define<DecorationSet>({
  create: buildMermaid,
  update(deco, tr) {
    if (
      tr.docChanged ||
      tr.selection ||
      tr.effects.some((e) => e.is(themeChanged) || e.is(diagramRendered)) ||
      // The incremental parser finished more of the doc (e.g. right after
      // the CRDT content lands) — fences may only now be visible.
      syntaxTree(tr.state) !== syntaxTree(tr.startState)
    ) {
      return buildMermaid(tr.state)
    }
    return deco
  },
  provide: (f) => EditorView.decorations.from(f),
})

/** ArrowDown/ArrowUp that would jump over a rendered diagram stops on its
 *  fence instead — the opening line going down, the closing line going up —
 *  which puts the selection on the fence and reveals the source. A move that
 *  doesn't cross a diagram (or a non-empty selection) falls through to the
 *  default motion.
 *
 *  Deliberately a keymap on the arrow KEYS, not a filter on cursor moves: a
 *  filter can't tell a one-line step from a jump that merely crosses the
 *  diagram (vim `:N`, `G`, a search, a heading link), and pulled those into
 *  the fence (1.9.4). Vim's own line motions are handled by `vimLineSteps`. */
function enterDiagram(forward: boolean) {
  return (view: EditorView): boolean => {
    const sel = view.state.selection.main
    if (!sel.empty) return false
    const next = view.moveVertically(sel, forward)
    let target: number | null = null
    view.state
      .field(mermaidField)
      .between(Math.min(sel.head, next.head), Math.max(sel.head, next.head), (from, to) => {
        const crosses = forward
          ? sel.head < from && next.head >= from
          : sel.head > to && next.head <= to
        if (!crosses) return undefined
        target = forward ? from : to
        return false
      })
    if (target === null) return false
    view.dispatch({ selection: { anchor: target }, scrollIntoView: true })
    return true
  }
}

const diagramArrows = Prec.high(
  keymap.of([
    { key: 'ArrowDown', run: enterDiagram(true) },
    { key: 'ArrowUp', run: enterDiagram(false) },
  ]),
)

/** True when `pos` falls inside a rendered (block-replaced) diagram. */
function inDiagram(decos: DecorationSet, pos: number): boolean {
  let hit = false
  decos.between(pos, pos, (from, to) => {
    hit = from <= pos && pos <= to
    return hit ? false : undefined
  })
  return hit
}

type VimCM = NonNullable<ReturnType<typeof getCM>>
const patchedVim = new WeakSet<VimCM>()

/** Vim's line motions (`j`/`k`, `6j`, `gj`) step through `findPosV`, one
 *  `moveVertically` per count — and a block widget is ONE such step, so `6j`
 *  above a diagram overshoots it entirely (vim then jumps to wherever that
 *  lands). Wrap the vim adapter's `findPosV` so a step into, inside, or out of
 *  a rendered diagram moves by one SOURCE line instead; steps elsewhere keep
 *  the stock visual-line behavior. Vim then lands on the logical line it
 *  counted (its goal column applies), and a cursor on a fence line reveals
 *  the diagram. Re-applied per vim instance, since toggling vim mode in the
 *  options panel builds a fresh one. */
const vimLineSteps = ViewPlugin.fromClass(
  class {
    constructor(view: EditorView) {
      this.patch(view)
    }
    update(u: ViewUpdate) {
      this.patch(u.view)
    }
    patch(view: EditorView) {
      const cm = getCM(view)
      if (!cm || patchedVim.has(cm)) return
      patchedVim.add(cm)
      const stock = cm.findPosV.bind(cm)
      cm.findPosV = (start, amount, unit, goalColumn) => {
        const decos = view.state.field(mermaidField)
        if (unit !== 'line' || decos.size === 0) return stock(start, amount, unit, goalColumn)
        const doc = view.state.doc
        const dir = amount > 0 ? 1 : -1
        let pos: ReturnType<typeof stock> = { line: start.line, ch: start.ch }
        for (let i = 0; i < Math.abs(Math.round(amount)); i++) {
          const next = pos.line + dir
          if (next < 0 || next >= doc.lines) return stock(pos, dir, unit, goalColumn)
          const here = doc.line(pos.line + 1)
          const there = doc.line(next + 1)
          if (inDiagram(decos, here.from) || inDiagram(decos, there.from)) {
            pos = { line: next, ch: Math.min(start.ch, there.length) }
          } else {
            pos = stock(pos, dir, unit, goalColumn)
          }
        }
        return pos
      }
    }
  },
)

/** Re-render on a light/dark switch — the palette is read from the live
 *  Catppuccin tokens at render time, so the cache is keyed by scheme. */
const themeWatcher = ViewPlugin.fromClass(
  class {
    mq: MediaQueryList | null
    onChange: () => void
    constructor(view: EditorView) {
      this.onChange = () => view.dispatch({ effects: themeChanged.of(null) })
      this.mq = window.matchMedia?.('(prefers-color-scheme: dark)') ?? null
      this.mq?.addEventListener('change', this.onChange)
    }
    destroy() {
      this.mq?.removeEventListener('change', this.onChange)
    }
  },
)

export function mermaidDiagrams() {
  return [mermaidField, themeWatcher, diagramArrows, vimLineSteps]
}
