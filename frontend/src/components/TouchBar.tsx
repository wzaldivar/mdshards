import { useEffect, useState } from 'react'
import type { ShortcutHandlers } from '../lib/shortcuts'
import styles from './TouchBar.module.css'

interface Props {
  /** The same handler bag the global keymap drives — the bar is a second
   *  trigger surface for the identical actions, never a parallel code path. */
  handlers: ShortcutHandlers
  /** Current path points at a real file: gates rename + delete, which would
   *  otherwise bubble a 404 from the backend. */
  exists: boolean
  /** Current path is a markdown note: gates the emoji picker, which needs a
   *  live buffer to insert into. */
  currentIsMd: boolean
}

interface Action {
  key: string
  /** Emoji glyph — the app already ships emoji rendering and this keeps the
   *  bar dependency-free (no icon set to pull in). */
  icon: string
  label: string
  run: (h: ShortcutHandlers) => void
  /** Which availability flag, if any, this action requires. */
  needs?: 'exists' | 'md'
}

const ACTIONS: Action[] = [
  { key: 'open', icon: '🔍', label: 'Open or create a note', run: (h) => h.openQuickSwitcher() },
  { key: 'emoji', icon: '😀', label: 'Insert emoji', run: (h) => h.openEmojiPicker(), needs: 'md' },
  { key: 'upload', icon: '📤', label: 'Upload a file', run: (h) => h.openUploadSwitcher() },
  { key: 'rename', icon: '✏️', label: 'Rename this file', run: (h) => h.openRenameSwitcher(), needs: 'exists' },
  { key: 'delete', icon: '🗑️', label: 'Delete a file', run: (h) => h.openDeleteSwitcher(), needs: 'exists' },
  { key: 'options', icon: '⚙️', label: 'Editor options', run: (h) => h.openOptions() },
]

/**
 * Keep the bar above the software keyboard.
 *
 * A `position: fixed; bottom: 0` element is laid out against the *layout*
 * viewport, which the on-screen keyboard does not shrink — so the bar ends up
 * underneath the keyboard exactly when the user is typing and most likely to
 * want it. The visual viewport DOES shrink, so the gap to lift by is
 * `layoutHeight - (visualHeight + visualOffsetTop)`.
 *
 * Returns 0 when there's no `visualViewport` (older browsers, jsdom) or no
 * keyboard is up, which leaves the plain bottom-anchored bar.
 */
function useKeyboardInset(): number {
  const [inset, setInset] = useState(0)
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv) return
    const update = (): void => {
      const gap = window.innerHeight - (vv.height + vv.offsetTop)
      // Sub-pixel noise and browser-chrome resizes shouldn't jitter the bar;
      // only a real keyboard (tens of px) clears the threshold.
      setInset(gap > 24 ? Math.round(gap) : 0)
    }
    update()
    vv.addEventListener('resize', update)
    vv.addEventListener('scroll', update)
    return () => {
      vv.removeEventListener('resize', update)
      vv.removeEventListener('scroll', update)
    }
  }, [])
  return inset
}

/**
 * The touch action bar — mdshards' answer to "there is no Cmd key here".
 *
 * Every vault operation is normally a Cmd/Ctrl chord (see `lib/shortcuts.ts`),
 * which a phone or tablet simply cannot produce. This bar exposes the same
 * `ShortcutHandlers` as tap targets so a keyboardless environment reaches the
 * quick switcher, emoji picker, upload, rename, delete, and options panel.
 *
 * It is rendered only when the environment is touch-primary — `EditorView`
 * gates it on `useTouchPrimary()`, so desktop keeps its uncluttered chrome.
 *
 * Focus handling: the action runs on `click`, but `mousedown` is
 * `preventDefault`ed. That's the standard rich-text-toolbar trick — suppressing
 * mousedown's default suppresses the focus change, so tapping the bar never
 * blurs the editor (on iOS a blur dismisses the software keyboard and jumps the
 * scroll position). `click` still fires normally, which matters for
 * accessibility: VoiceOver / TalkBack activation and keyboard Enter/Space
 * dispatch a click and never a pointer event, so binding the action to click is
 * what keeps the bar reachable by assistive tech.
 */
export function TouchBar({ handlers, exists, currentIsMd }: Readonly<Props>) {
  const keyboardInset = useKeyboardInset()

  return (
    <nav
      className={styles.bar}
      style={{ bottom: keyboardInset }}
      aria-label="Editor actions"
    >
      {ACTIONS.map((action) => {
        let disabled = false
        if (action.needs === 'exists') disabled = !exists
        if (action.needs === 'md') disabled = !currentIsMd
        return (
          <button
            key={action.key}
            type="button"
            className={styles.button}
            disabled={disabled}
            aria-label={action.label}
            title={action.label}
            // Keep focus (and the software keyboard) where it is; see above.
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => action.run(handlers)}
          >
            <span aria-hidden="true">{action.icon}</span>
          </button>
        )
      })}
    </nav>
  )
}
