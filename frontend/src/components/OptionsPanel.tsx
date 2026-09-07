import { useEffect, useState } from 'react'
import {
  getEditorPrefs,
  setEditorPref,
  subscribeEditorPrefs,
  type EditorPrefs,
} from '../lib/editor-prefs'
import { useTouchPrimary } from '../lib/touch'
import styles from './OptionsPanel.module.css'

interface Props {
  open: boolean
  onClose: () => void
}

interface Row {
  key: keyof EditorPrefs
  /** `KeyboardEvent.code` for the ⌥-accelerator (Alt mangles `.key` on macOS). */
  code: string
  /** Display label for the accelerator chip. */
  accel: string
  label: string
  hint: string
  /** When set, the row is only meaningful if this other pref is on. */
  requires?: keyof EditorPrefs
  /** Rows whose feature presupposes a desktop are hidden on touch-primary
   *  devices — offering a toggle whose effect is clamped away in
   *  `editor-prefs` would just read as broken. Each such row's reason is on
   *  the row itself; see `getEditorPrefs` for the matching clamp. */
  desktopOnly?: boolean
}

const ROWS: Row[] = [
  {
    key: 'vim',
    code: 'KeyV',
    accel: '⌥V',
    label: 'Vim mode',
    hint: 'Modal editing (NORMAL / INSERT / VISUAL)',
    // No software keyboard can drive modal editing (no Escape / `:` / hjkl).
    desktopOnly: true,
  },
  {
    key: 'lineNumbers',
    code: 'KeyN',
    accel: '⌥N',
    label: 'Show line numbers',
    hint: 'Line-number gutter',
  },
  {
    key: 'relativeLineNumbers',
    code: 'KeyR',
    accel: '⌥R',
    label: 'Relative line numbers',
    hint: 'Distance from the cursor line',
    requires: 'lineNumbers',
  },
  {
    key: 'centerLine',
    code: 'KeyC',
    accel: '⌥C',
    label: 'Center current line',
    hint: 'Keep the cursor line vertically centered (except near file edges)',
    // Centring is meaningless on a phone: the software keyboard covers the
    // area the line would be centered into, and re-centering on every tap
    // fights the browser's own caret scrolling.
    desktopOnly: true,
  },
]

/** Editor options (Cmd/Ctrl-Alt-O). Each toggle is a local preference persisted
 * to localStorage; the live editor re-applies via the prefs pub/sub. */
export function OptionsPanel({ open, onClose }: Readonly<Props>) {
  const [prefs, setPrefs] = useState<EditorPrefs>(getEditorPrefs)
  // Touch device -> drop the rows whose feature presupposes a desktop (vim,
  // centre-line — both clamped off in editor-prefs too), drop the
  // Alt-accelerator chrome, and offer a tappable Close since there's no
  // Escape key.
  const touchPrimary = useTouchPrimary()
  const rows = touchPrimary ? ROWS.filter((r) => !r.desktopOnly) : ROWS

  // While open, stay in sync with the prefs store: re-read on open, then track
  // changes (including cross-tab `storage` events) so the checkboxes reflect
  // toggles made in other tabs live.
  useEffect(() => {
    if (!open) return
    setPrefs(getEditorPrefs())
    return subscribeEditorPrefs(setPrefs)
  }, [open])

  // Keyboard control while open, in the capture phase so it beats CodeMirror /
  // vim: Escape closes; ⌥V / ⌥N / ⌥R toggle the rows. Prefs are read fresh in
  // the handler (not from `prefs`) so it never toggles a stale value and the
  // listener doesn't re-bind on every change.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        onClose()
        return
      }
      // Match on `e.code` — Alt+letter yields a special char in `e.key` on macOS.
      if (e.altKey && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
        const row = ROWS.find((r) => r.code === e.code)
        if (!row) return
        const cur = getEditorPrefs()
        if (row.requires && !cur[row.requires]) return // row is disabled
        e.preventDefault()
        e.stopPropagation()
        setEditorPref(row.key, !cur[row.key])
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [open, onClose])

  if (!open) return null

  const toggle = (key: keyof EditorPrefs): void => {
    // The subscription above reflects the write back into `prefs`.
    setEditorPref(key, !prefs[key])
  }

  return (
    <div className={styles.backdrop}>
      {/* Native <button> close-catcher; see QuickSwitcher for the rationale. */}
      <button type="button" className={styles.scrim} aria-label="Close" tabIndex={-1} onClick={onClose} />
      {/* Native <dialog> (open, non-modal) instead of a div with
          role="dialog" (S6819). Kept non-modal — the custom backdrop/scrim
          above handles the overlay/close; `open` just makes it visible. */}
      <dialog className={styles.modal} aria-label="Editor options" open>
        <div className={styles.header}>Editor options</div>
        <ul className={styles.list}>
          {rows.map((row) => {
            const disabled = row.requires ? !prefs[row.requires] : false
            return (
              <li key={row.key} className={styles.item}>
                <label className={`${styles.row} ${disabled ? styles.disabled : ''}`}>
                  <input
                    type="checkbox"
                    checked={prefs[row.key]}
                    disabled={disabled}
                    onChange={() => toggle(row.key)}
                  />
                  <span className={styles.text}>
                    <span className={styles.label}>{row.label}</span>
                    <span className={styles.hint}>{row.hint}</span>
                  </span>
                  {!touchPrimary && <span className={styles.accel}>{row.accel}</span>}
                </label>
              </li>
            )
          })}
        </ul>
        <div className={styles.footer}>
          {touchPrimary ? (
            <button type="button" className={styles.closeBtn} onClick={onClose}>
              Close
            </button>
          ) : (
            <>
              <span className={styles.kbd}>Esc</span> to close
            </>
          )}
        </div>
      </dialog>
    </div>
  )
}
