import { useEffect, useState } from 'react'
import { getEditorPrefs, setEditorPref, type EditorPrefs } from '../lib/editor-prefs'
import styles from './OptionsPanel.module.css'

interface Props {
  open: boolean
  onClose: () => void
}

interface Row {
  key: keyof EditorPrefs
  label: string
  hint: string
  /** When set, the row is only meaningful if this other pref is on. */
  requires?: keyof EditorPrefs
}

const ROWS: Row[] = [
  { key: 'vim', label: 'Vim mode', hint: 'Modal editing (NORMAL / INSERT / VISUAL)' },
  { key: 'lineNumbers', label: 'Show line numbers', hint: 'Line-number gutter' },
  {
    key: 'relativeLineNumbers',
    label: 'Relative line numbers',
    hint: 'Distance from the cursor line',
    requires: 'lineNumbers',
  },
]

/** Editor options (Cmd/Ctrl-Alt-O). Each toggle is a local preference persisted
 * to localStorage; the live editor re-applies via the prefs pub/sub. */
export function OptionsPanel({ open, onClose }: Props) {
  const [prefs, setPrefs] = useState<EditorPrefs>(getEditorPrefs)

  // Re-read from storage each time the panel opens so it reflects any change
  // made elsewhere while it was closed.
  useEffect(() => {
    if (open) setPrefs(getEditorPrefs())
  }, [open])

  // Escape closes. Capture phase so it beats CodeMirror / vim's own Escape.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        onClose()
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [open, onClose])

  if (!open) return null

  const toggle = (key: keyof EditorPrefs): void => {
    const next = !prefs[key]
    setEditorPref(key, next)
    setPrefs((p) => ({ ...p, [key]: next }))
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
