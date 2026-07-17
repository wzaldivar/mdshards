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
import { Autolink, Strikethrough, Subscript, Superscript, Table, TaskList } from '@lezer/markdown'
import { blockquote, codeblock, hideMarks, htmlBlock, lists } from '@retronav/ixora'
import { yCollab } from 'y-codemirror.next'
import { catppuccinHighlight } from '../lib/cm-highlight'
import { closeDoc, fetchServerConfig, openDoc, type DocBundle } from '../lib/crdt'
import { shortcodeTokenAt } from '../lib/emoji'
import { EmojiShortcode } from '../lib/md-emoji'
import { Highlight } from '../lib/md-highlight'
import { markdownLive } from '../lib/markdown-live'
import { pendingRenames } from '../lib/pending-rename'
import {
  getEditorPrefs,
  subscribeEditorPrefs,
  type EditorPrefs,
} from '../lib/editor-prefs'
import { Wikilink } from '../lib/wikilink'
import { encodePathToUrl } from '../lib/paths'
import { centerCurrentLine } from '../lib/typewriter'
import styles from './Editor.module.css'

// Must match the constants in backend/app/docs.py.
const DOC_DELETED_CODE = 4001
const DOC_MOVED_CODE = 4002

/** Imperative surface EditorView reaches through to touch the live buffer —
 *  the emoji picker's context probe + insertion. Populated on mount, nulled
 *  on teardown. */
export interface EditorApi {
  /** The `:shortcode` token the cursor is touching, colons stripped — the
   *  picker's seed query — or null when the cursor isn't on one. */
  emojiQueryAtCursor: () => string | null
  /** Write `:name:` into the buffer: replaces the whole shortcode token the
   *  cursor touches (half-typed `:smi`, typo'd `:zmile:`, or a valid one
   *  being swapped), else inserts at the cursor. Refocuses the editor. */
  insertShortcode: (name: string) => void
  /** Write a literal UTF-8 glyph into the buffer — the Shift-Enter variant of
   *  the picker. Same token-replace / insert rule as `insertShortcode`, but
   *  the glyph lands as-is (no `:code:`); it stays a plain character on disk
   *  (`:code:`→glyph rendering never runs on it — there is no reverse
   *  substitution). Refocuses the editor. */
  insertGlyph: (glyph: string) => void
  /** Refocus the buffer — used when a modal opened from the editor closes
   *  without acting, so typing can resume where it left off. */
  focus: () => void
}

interface Props {
  docId: string
  onMoved: (target: string) => void
  /** Called with `true` when a lost connection outlasts the grace window and
   *  the buffer is locked read-only, and `false` once editing is restored. */
  onReadOnlyChange: (readOnly: boolean) => void
  /** Receives the imperative editor API while a buffer is mounted. */
  apiRef?: React.MutableRefObject<EditorApi | null>
}

export function Editor({ docId, onMoved, onReadOnlyChange, apiRef }: Readonly<Props>) {
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
    // The provider is created with `connect: false` (see openDoc) and the
    // socket is opened one task later. A mount that is torn down within the
    // same tick — StrictMode's double-invoke, rapid navigation — therefore
    // never opens a WebSocket, so no socket is ever closed mid-handshake.
    // Safari wedges on exactly that: an aborted CONNECTING socket can stall
    // the next connection to the same URL indefinitely.
    let connectTimer: ReturnType<typeof setTimeout> | null = null
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
    const centerLine = new Compartment()
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
      const effects = [
        // `vim()` must lead the extension list, so its compartment is placed
        // first in buildView; reconfiguring in place keeps that slot.
        vimMode.reconfigure(prefs.vim ? vim() : []),
        lineGutter.reconfigure(lineNumberExtensions(prefs)),
        centerLine.reconfigure(centerLineExtension(prefs)),
      ]
      // Centering only reacts to future cursor moves, so re-center once now for
      // immediate feedback when the toggle is flipped on.
      if (prefs.centerLine && view) {
        effects.push(EditorView.scrollIntoView(view.state.selection.main.head, { y: 'center' }))
      }
      view?.dispatch({ effects })
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
      // Always (re)assert the banner state, even when `ro` matches the current
      // `readOnly` — that's what lets a stranded banner self-heal on the next
      // reconnect (a within-grace reconnect calls setReadOnly(false); if the
      // banner had drifted to `true` while `readOnly` was already `false`, an
      // early `return` here would leave it stuck). The editable dispatch is the
      // only expensive part, so guard just that. `finally` guarantees the
      // banner notification fires even if the dispatch throws mid-teardown.
      try {
        if (ro !== readOnly) {
          readOnly = ro
          view?.dispatch({
            effects: editable.reconfigure(
              ro ? [EditorView.editable.of(false), EditorState.readOnly.of(true)] : [],
            ),
          })
        }
      } finally {
        onReadOnlyChangeRef.current(ro)
      }
    }

    // The "offline dino" is a function of (tab visible AND actually offline
    // past grace), NOT a fire-and-forget timer. A hidden tab gets its timers
    // throttled and isn't being edited — running the read-only countdown there
    // is what made the banner strand/flap after trivial background blips. So we
    // pause the countdown while hidden and only ever lock a tab the user is
    // actually looking at.
    const lockReadOnlyIfStillDown = (): void => {
      // Countdown elapsed — only lock if we're genuinely still offline. Guards
      // against a reconnect that recovered the socket without us catching a
      // 'connected' status event (and against a throttled timer firing late).
      // No bundle means no live editor (torn down mid-countdown) — there is
      // nothing to lock, and locking would strand the banner on a page whose
      // Editor can never clear it.
      if (bundle && !bundle.provider.wsconnected) setReadOnly(true)
    }

    const onVisibilityChange = (): void => {
      if (document.visibilityState === 'hidden') {
        // Don't count down toward read-only for a tab nobody's editing; the
        // throttled timer would fire late and strand the banner. Re-decide on
        // refocus based on the actual socket state.
        clearReadOnlyTimer()
        return
      }
      // Refocused: if still offline, give the socket a fresh full window to
      // reconnect before locking (throttling just lifted, so a reconnect is
      // imminent). If it already reconnected, the 'connected' handler cleared
      // the timer / unlocked, and wsconnected is true so we no-op.
      if (bundle && !bundle.provider.wsconnected) {
        clearReadOnlyTimer()
        readOnlyTimer = setTimeout(lockReadOnlyIfStillDown, staleAfterMs)
      }
    }

    const teardown = (): void => {
      if (apiRef) apiRef.current = null
      if (connectTimer !== null) {
        clearTimeout(connectTimer)
        connectTimer = null
      }
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
      navigate('/' + encodePathToUrl(clean))
    }

    // A reconnect past the grace window means the in-memory Doc we hold is
    // stale (the server no longer has it), so rebuild from scratch. Deferred to
    // a microtask so we're not tearing down the provider from inside its own
    // 'status' event. Hoisted out of the status handler to keep that callback's
    // nesting shallow.
    const scheduleStaleRemount = (): void => {
      remounting = true
      queueMicrotask(() => {
        teardown()
        mount()
        remounting = false
      })
    }
    const mount = (): void => {
      // A freshly-built view is editable and (re)connecting, so clear any
      // lingering read-only lock and its banner. This is the belt that stops a
      // stale "connection lost" banner from surviving the stale-reconnect
      // remount below: the recovered view is editable and syncing again, so the
      // banner must not stick. Set directly (not via setReadOnly) so it fires
      // even when `readOnly` was already reset but the banner wasn't cleared.
      readOnly = false
      onReadOnlyChangeRef.current(false)
      bundle = openDoc(docId)
      const b = bundle
      connectTimer = setTimeout(() => {
        connectTimer = null
        b.provider.connect()
      }, 0)
      startHeartbeat(bundle)
      // Every provider event handler below must first drop events from a
      // torn-down bundle (`bundle !== b`). closeDoc() closes the socket but
      // the WebSocket 'close' event arrives on a LATER task — after teardown
      // already ran clearReadOnlyTimer(). Without the guard, that late
      // 'disconnected' event re-arms the 25s read-only countdown as a zombie
      // no cleanup will ever cancel, and it locks the banner on whatever page
      // the user has navigated to since — including asset pages, where no
      // Editor exists to ever clear it again.
      bundle.provider.on('connection-close', (event: CloseEvent | null) => {
        if (bundle !== b) return
        if (!event) return
        if (event.code === DOC_DELETED_CODE) {
          // Server kicked us because the file was deleted — bail to root so we
          // don't immediately reconnect to a doc that no longer exists.
          teardown()
          navigate('/')
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
        if (bundle !== b) return
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
          scheduleStaleRemount()
        } else if (event.status === 'disconnected' && disconnectedAt === null) {
          disconnectedAt = Date.now()
          // Keep editing during a blip, but once the outage outlasts the grace
          // window the Doc we hold is stale — lock the buffer read-only. A later
          // reconnect either unlocks (within grace) or remounts a fresh Doc.
          // Only count down while the tab is visible; onVisibilityChange
          // (re)starts the countdown on refocus if we're still offline.
          clearReadOnlyTimer()
          if (document.visibilityState === 'visible') {
            readOnlyTimer = setTimeout(lockReadOnlyIfStillDown, staleAfterMs)
          }
        }
      })
      view = buildView(host, bundle, docId, onWikilinkNavigate, editable, {
        vimMode,
        lineGutter,
        centerLine,
        prefs,
      })
      syncVimStatus()
      if (apiRef) {
        // Both calls scan at CALL time relative to the current cursor —
        // the modal keeps the editor blurred (selection frozen), so the
        // token found on open is the one replaced on pick even if remote
        // CRDT edits shifted absolute positions meanwhile.
        const tokenAtCursor = () => {
          if (!view) return null
          const head = view.state.selection.main.head
          const line = view.state.doc.lineAt(head)
          const token = shortcodeTokenAt(line.text, head - line.from)
          return token ? { ...token, from: line.from + token.start, to: line.from + token.end } : null
        }
        // Shared by both picker actions: replace the touched shortcode token
        // (if any) with `text`, else insert at the cursor. Only the inserted
        // string differs — `:name:` for Enter, the glyph for Shift-Enter.
        const replaceTokenOrInsert = (text: string) => {
          if (!view || readOnly) return
          const token = tokenAtCursor()
          const sel = view.state.selection.main
          const from = token ? token.from : sel.from
          const to = token ? token.to : sel.to
          view.dispatch({
            changes: { from, to, insert: text },
            selection: { anchor: from + text.length },
          })
          view.focus()
        }
        apiRef.current = {
          focus: () => view?.focus(),
          emojiQueryAtCursor: () => tokenAtCursor()?.query ?? null,
          insertShortcode: (name: string) => replaceTokenOrInsert(`:${name}:`),
          insertGlyph: (glyph: string) => replaceTokenOrInsert(glyph),
        }
      }
    }

    document.addEventListener('visibilitychange', onVisibilityChange)
    mount()
    // Effect-level cleanup: drop the visibility + prefs subscriptions (which
    // must outlive the stale-reconnect remount that reuses `teardown` on its
    // own) then teardown.
    return () => {
      document.removeEventListener('visibilitychange', onVisibilityChange)
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

function centerLineExtension(prefs: EditorPrefs) {
  return prefs.centerLine ? centerCurrentLine : []
}

interface EditorCompartments {
  vimMode: Compartment
  lineGutter: Compartment
  centerLine: Compartment
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
      // Typewriter scrolling — compartmentalized so the Options panel toggles it live.
      cfg.centerLine.of(centerLineExtension(cfg.prefs)),
      // Editability toggle — starts open, flipped read-only on a past-grace
      // disconnect (see the effect above).
      editable.of([]),
      history(),
      drawSelection(),
      keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
      // GFM-style: Table (without this, the `---` row inside a table is
      // mis-parsed as a horizontal rule and the table fragments visually),
      // TaskList, Strikethrough, and Autolink. Extended syntax: Subscript
      // (`H~2~O`), Superscript (`x^2^`), and our own Highlight (`==text==`,
      // lib/md-highlight.ts). Plus our Wikilink inline parser for `[[…]]`.
      //
      // `codeLanguages` enables per-language syntax highlighting inside
      // fenced code blocks (` ```python `, ` ```ts `, etc.). The
      // language-data package ships LanguageDescription entries with lazy
      // dynamic-import thunks, so the initial bundle stays small — each
      // language pack only loads when a code block actually references it,
      // then the existing `catppuccinHighlight` style colours the tokens.
      markdown({
        extensions: [Table, TaskList, Strikethrough, Subscript, Superscript, Highlight, EmojiShortcode, Autolink, Wikilink],
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
