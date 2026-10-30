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
 * Arrowing up/down into a diagram reveals it like a table or image: CodeMirror
 * moves vertically PAST a block widget, so `enterDiagram` catches a move that
 * would skip one and lands on its fence instead. The file always keeps the literal fence — the
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
  WidgetType,
} from '@codemirror/view'
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

function getRendered(source: string, dark: boolean): Rendered | Promise<Rendered> {
  const key = `${dark ? 'd' : 'l'}\0${source}`
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
  constructor(source: string, dark: boolean) {
    super()
    this.source = source
    this.dark = dark
  }
  override eq(other: MermaidWidget): boolean {
    return other.source === this.source && other.dark === this.dark
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
        // The block's height changed under CodeMirror — re-measure so
        // vertical motion and scrolling use the real geometry.
        view.requestMeasure()
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
      tr.effects.some((e) => e.is(themeChanged)) ||
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
 *  default motion. */
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
  return [mermaidField, themeWatcher, diagramArrows]
}
