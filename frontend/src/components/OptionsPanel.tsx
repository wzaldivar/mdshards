import { useEffect, useState } from 'react'
import {
  getEditorPrefs,
  setEditorPref,
  subscribeEditorPrefs,
  type EditorPrefs,
} from '../lib/editor-prefs'
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
}

const ROWS: Row[] = [
  {
    key: 'vim',
    code: 'KeyV',
    accel: '⌥V',
    label: 'Vim mode',
    hint: 'Modal editing (NORMAL / INSERT / VISUAL)',
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
  },
]

/** Editor options (Cmd/Ctrl-Alt-O). Each toggle is a local preference persisted
 * to localStorage; the live editor re-applies via the prefs pub/sub. */
export function OptionsPanel({ open, onClose }: Props) {
  const [prefs, setPrefs] = useState<EditorPrefs>(getEditorPrefs)

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
    <div className={styles.backdrop} onClick={onClose}>
      <div
        className={styles.modal}
        role="dialog"
        aria-label="Editor options"
        onClick={(e) => e.stopPropagation()}
      >
        <div className={styles.header}>Editor options</div>
        <ul className={styles.list}>
          {ROWS.map((row) => {
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
                  <span className={styles.accel}>{row.accel}</span>
                </label>
              </li>
            )
          })}
        </ul>
        <div className={styles.footer}>
          <span className={styles.kbd}>Esc</span> to close
        </div>
      </div>
    </div>
  )
}
