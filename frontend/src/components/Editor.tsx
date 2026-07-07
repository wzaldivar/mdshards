import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { Compartment, EditorState } from '@codemirror/state'
import {
  drawSelection,
  EditorView,
  highlightActiveLineGutter,
  keymap,
  lineNumbers,
} from '@codemirror/view'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { getCM, vim } from '@replit/codemirror-vim'
import { syntaxHighlighting } from '@codemirror/language'
import { languages as codeLanguages } from '@codemirror/language-data'
import { markdown } from '@codemirror/lang-markdown'
import { Autolink, Strikethrough, Table, TaskList } from '@lezer/markdown'
import { blockquote, codeblock, hideMarks, htmlBlock, lists } from '@retronav/ixora'
import { yCollab } from 'y-codemirror.next'
import { catppuccinHighlight } from '../lib/cm-highlight'
import { closeDoc, fetchServerConfig, openDoc, type DocBundle } from '../lib/crdt'
import { markdownLive } from '../lib/markdown-live'
import { pendingRenames } from '../lib/pending-rename'
import {
  getEditorPrefs,
  subscribeEditorPrefs,
  type EditorPrefs,
} from '../lib/editor-prefs'
import { Wikilink } from '../lib/wikilink'
import styles from './Editor.module.css'

// Must match the constants in backend/app/docs.py.
const DOC_DELETED_CODE = 4001
const DOC_MOVED_CODE = 4002

interface Props {
  docId: string
  onMoved: (target: string) => void
  /** Called with `true` when a lost connection outlasts the grace window and
   *  the buffer is locked read-only, and `false` once editing is restored. */
  onReadOnlyChange: (readOnly: boolean) => void
}

export function Editor({ docId, onMoved, onReadOnlyChange }: Props) {
  const navigate = useNavigate()
  const hostRef = useRef<HTMLDivElement | null>(null)
  // Current vim mode label (NORMAL/INSERT/VISUAL/REPLACE), or null when vim is
  // off — drives the little corner indicator.
  const [vimStatus, setVimStatus] = useState<string | null>(null)
  // Latest-callback refs so changing these props doesn't re-mount CodeMirror.
  const onMovedRef = useRef(onMoved)
  const onReadOnlyChangeRef = useRef(onReadOnlyChange)
  useEffect(() => {
    onMovedRef.current = onMoved
    onReadOnlyChangeRef.current = onReadOnlyChange
  }, [onMoved, onReadOnlyChange])

  useEffect(() => {
    const host = hostRef.current
    if (!host) return

    let bundle: DocBundle | null = null
    let view: EditorView | null = null
    let remounting = false
    let heartbeatTimer: ReturnType<typeof setInterval> | null = null
    // Short blips reconnect against the same in-memory server-side Doc and
    // resync cleanly. Once the disconnect exceeds the server's grace window the
    // server will have rebuilt the Doc from disk with fresh item IDs, and a
    // reconnect would merge those new items on top of the items we already have,
    // duplicating content. Only remount in that case. The threshold tracks the
    // server's actual setting via /api/config, with a small safety margin.
    let staleAfterMs = 25_000
    void fetchServerConfig().then((cfg) => {
      staleAfterMs = Math.max(5_000, cfg.gracePeriodSeconds * 1000 - 5_000)
    })

    const stopHeartbeat = (): void => {
      if (heartbeatTimer !== null) {
        clearInterval(heartbeatTimer)
        heartbeatTimer = null
      }
    }

    const startHeartbeat = (b: DocBundle): void => {
      stopHeartbeat()
      // Browsers throttle setInterval in backgrounded tabs (~1/min), but that's
      // still well under the server's grace, so an awareness ping at 30s is plenty
      // to keep the Doc resident on the server while this tab is alive.
      heartbeatTimer = setInterval(() => {
        if (b.provider.wsconnected) {
          b.provider.awareness.setLocalStateField('heartbeat', Date.now())
        }
      }, 30_000)
    }

    // Editability is swapped through a compartment so the buffer can be locked
    // without rebuilding the view. Past the grace window a lost connection
    // means the server has moved on from our Doc, so we stop accepting edits
    // (offline is a hard stop, not an offline-editing mode — see CLAUDE.md) and
    // surface a "lost the server" banner until we reconnect.
    const editable = new Compartment()
    let readOnlyTimer: ReturnType<typeof setTimeout> | null = null
    let readOnly = false

    // Local editor preferences (vim, line numbers) each ride their own
    // compartment so the Options panel (Cmd-Alt-O) can flip them live without
    // rebuilding the view. `prefs` is re-read from storage per effect run, so
    // it survives the stale-reconnect remount below and re-reads on navigation.
    const vimMode = new Compartment()
    const lineGutter = new Compartment()
    let prefs = getEditorPrefs()

    const onVimModeChange = (e: { mode: string }): void => {
      setVimStatus(e.mode.toUpperCase())
    }
    // Seed the indicator label and (re)attach the mode-change listener. Called
    // after each view build and whenever vim turns on, because reconfiguring
    // the compartment builds a fresh vim instance whose events we re-subscribe.
    const syncVimStatus = (): void => {
      if (!prefs.vim) {
        setVimStatus(null)
        return
      }
      setVimStatus('NORMAL') // vim always (re)starts in normal mode
      const cm = view ? getCM(view) : null
      cm?.on('vim-mode-change', onVimModeChange)
    }

    // Apply a preference snapshot to the live view. Driven by the prefs pub/sub
    // (Options panel) and called once after each view build.
    const applyPrefs = (next: EditorPrefs): void => {
      prefs = next
      view?.dispatch({
        effects: [
          // `vim()` must lead the extension list, so its compartment is placed
          // first in buildView; reconfiguring in place keeps that slot.
          vimMode.reconfigure(prefs.vim ? vim() : []),
          lineGutter.reconfigure(lineNumberExtensions(prefs)),
        ],
      })
      syncVimStatus()
    }

    const unsubscribePrefs = subscribeEditorPrefs(applyPrefs)

    const clearReadOnlyTimer = (): void => {
      if (readOnlyTimer !== null) {
        clearTimeout(readOnlyTimer)
        readOnlyTimer = null
      }
    }

    const setReadOnly = (ro: boolean): void => {
      if (ro === readOnly) return
      readOnly = ro
      view?.dispatch({
        effects: editable.reconfigure(
          ro ? [EditorView.editable.of(false), EditorState.readOnly.of(true)] : [],
        ),
      })
      onReadOnlyChangeRef.current(ro)
    }

    const teardown = (): void => {
      clearReadOnlyTimer()
      // Clear the banner before dropping the view — covers both a stale-reconnect
      // remount (mount() rebuilds an editable view right after) and unmount.
      setReadOnly(false)
      stopHeartbeat()
      view?.destroy()
      view = null
      if (bundle) {
        closeDoc(bundle)
        bundle = null
      }
    }

    // Wiki links route through react-router so navigating to `[[notes/today]]`
    // is a SPA push, not a full page load. Strip any accidental leading slash
    // so the doc-id form matches the URL form.
    const onWikilinkNavigate = (target: string): void => {
      const clean = target.replace(/^\/+/, '')
      void navigate('/' + clean)
    }

    const mount = (): void => {
      bundle = openDoc(docId)
      startHeartbeat(bundle)
      bundle.provider.on('connection-close', (event: CloseEvent | null) => {
        if (!event) return
        if (event.code === DOC_DELETED_CODE) {
          // Server kicked us because the file was deleted — bail to root so we
          // don't immediately reconnect to a doc that no longer exists.
          teardown()
          void navigate('/')
        } else if (event.code === DOC_MOVED_CODE) {
          const target = event.reason ?? ''
          if (pendingRenames.has(target)) {
            // We initiated the rename — RenameSwitcher already kicked off the
            // navigation. Just stop driving this editor; the route change will
            // unmount us via the parent's key.
            pendingRenames.delete(target)
            teardown()
          } else {
            // Someone else moved this doc. Let the user choose whether to follow.
            onMovedRef.current(target)
          }
        }
      })
      let everConnected = false
      let disconnectedAt: number | null = null
      bundle.provider.on('status', (event: { status: string }) => {
        if (event.status === 'connected') {
          clearReadOnlyTimer()
          if (!everConnected) {
            everConnected = true
            disconnectedAt = null
            return
          }
          const downFor = disconnectedAt === null ? 0 : Date.now() - disconnectedAt
          disconnectedAt = null
          if (downFor <= staleAfterMs || remounting) {
            // Blip within grace: the server still holds our Doc and y-websocket
            // resynced it cleanly. Unlock editing if the timer had fired.
            setReadOnly(false)
            return
          }
          remounting = true
          queueMicrotask(() => {
            teardown()
            mount()
            remounting = false
          })
        } else if (event.status === 'disconnected' && disconnectedAt === null) {
          disconnectedAt = Date.now()
          // Keep editing during a blip, but once the outage outlasts the grace
          // window the Doc we hold is stale — lock the buffer read-only. A later
          // reconnect either unlocks (within grace) or remounts a fresh Doc.
          clearReadOnlyTimer()
          readOnlyTimer = setTimeout(() => setReadOnly(true), staleAfterMs)
        }
      })
      view = buildView(host, bundle, docId, onWikilinkNavigate, editable, {
        vimMode,
        lineGutter,
        prefs,
      })
      syncVimStatus()
    }

    mount()
    // Effect-level cleanup: drop the prefs subscription (which must outlive the
    // stale-reconnect remount that reuses `teardown` on its own) then teardown.
    return () => {
      unsubscribePrefs()
      teardown()
    }
  }, [docId, navigate])

  return (
    <>
      <div ref={hostRef} className={styles.host} />
      {vimStatus && (
        <div className={styles.vimBadge} data-mode={vimStatus} aria-live="polite">
          {vimStatus}
        </div>
      )}
    </>
  )
}

/** Line-number gutter extensions for a preference snapshot. Relative numbering
 * is hybrid (absolute on the cursor line, distance elsewhere); it's paired with
 * `highlightActiveLineGutter()` because the line-number gutter only recomputes
 * `formatNumber` when its gutter markers change — the active-line class shifting
 * with the cursor is what forces that recompute on vertical movement. */
function lineNumberExtensions(prefs: EditorPrefs) {
  if (!prefs.lineNumbers) return []
  if (!prefs.relativeLineNumbers) return [lineNumbers()]
  return [
    lineNumbers({
      formatNumber: (n, state) => {
        const cur = state.doc.lineAt(state.selection.main.head).number
        return n === cur ? String(n) : String(Math.abs(n - cur))
      },
    }),
    highlightActiveLineGutter(),
  ]
}

interface EditorCompartments {
  vimMode: Compartment
  lineGutter: Compartment
  prefs: EditorPrefs
}

function buildView(
  host: HTMLDivElement,
  bundle: DocBundle,
  docId: string,
  onNavigate: (target: string) => void,
  editable: Compartment,
  cfg: EditorCompartments,
): EditorView {
  const state = EditorState.create({
    doc: bundle.text.toString(),
    extensions: [
      // Vim mode MUST be the first extension (the @replit/codemirror-vim
      // requirement) so its keymap outranks the defaults below. Held in a
      // compartment so the Options panel can swap it in/out without a rebuild.
      cfg.vimMode.of(cfg.prefs.vim ? vim() : []),
      // Line-number gutter — also compartmentalized for live toggling.
      cfg.lineGutter.of(lineNumberExtensions(cfg.prefs)),
      // Editability toggle — starts open, flipped read-only on a past-grace
      // disconnect (see the effect above).
      editable.of([]),
      history(),
      drawSelection(),
      keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
      // GFM-style: Table (without this, the `---` row inside a table is
      // mis-parsed as a horizontal rule and the table fragments visually),
      // TaskList, Strikethrough, and Autolink. Plus our Wikilink inline
      // parser for `[[…]]` syntax.
      //
      // `codeLanguages` enables per-language syntax highlighting inside
      // fenced code blocks (` ```python `, ` ```ts `, etc.). The
      // language-data package ships LanguageDescription entries with lazy
      // dynamic-import thunks, so the initial bundle stays small — each
      // language pack only loads when a code block actually references it,
      // then the existing `catppuccinHighlight` style colours the tokens.
      markdown({
        extensions: [Table, TaskList, Strikethrough, Autolink, Wikilink],
        codeLanguages,
      }),
      syntaxHighlighting(catppuccinHighlight, { fallback: true }),
      // ixora handles the structural primitives that don't have project-
      // specific behavior — inline mark hiding, list bullets + interactive
      // task checkboxes, blockquote and code-block styling. The custom
      // `markdownLive` extension layers on top for the parts where our rules
      // diverge from CommonMark/Obsidian defaults: strict ATX heading
      // context, vault-relative asset paths for images, vault-relative
      // clickable links, and the `---` → divider rendering.
      hideMarks(),
      lists(),
      blockquote(),
      codeblock(),
      htmlBlock,
      markdownLive({ noteDocId: docId, onNavigate }),
      yCollab(bundle.text, bundle.provider.awareness),
      EditorView.lineWrapping,
    ],
  })
  return new EditorView({ state, parent: host })
}
