/**
 * Local editor preferences (the Options panel, Cmd/Ctrl-Alt-O).
 *
 * This is the app's only persistent client storage. CLAUDE.md's "no persistent
 * client storage" rule is about never shadowing vault/document state on the
 * client (no IndexedDB/PouchDB/etc.); a handful of small editor toggles are a
 * deliberate, documented exception — they never hold vault data and their loss
 * only reverts the editor to defaults.
 *
 * Values live under individual `mdshards:*` keys. A tiny pub/sub lets the live
 * editor re-apply compartments the moment the panel flips a toggle, without
 * either side reaching into the other.
 */

export interface EditorPrefs {
  vim: boolean
  lineNumbers: boolean
  relativeLineNumbers: boolean
}

const KEYS: Record<keyof EditorPrefs, string> = {
  vim: 'mdshards:vim',
  lineNumbers: 'mdshards:lineNumbers',
  relativeLineNumbers: 'mdshards:relativeLineNumbers',
}

function read(key: string): boolean {
  try {
    return localStorage.getItem(key) === '1'
  } catch {
    return false
  }
}

export function getEditorPrefs(): EditorPrefs {
  return {
    vim: read(KEYS.vim),
    lineNumbers: read(KEYS.lineNumbers),
    relativeLineNumbers: read(KEYS.relativeLineNumbers),
  }
}

const listeners = new Set<(prefs: EditorPrefs) => void>()

export function setEditorPref(key: keyof EditorPrefs, on: boolean): void {
  try {
    localStorage.setItem(KEYS[key], on ? '1' : '0')
  } catch {
    /* storage unavailable — preference just won't persist this session */
  }
  const snapshot = getEditorPrefs()
  for (const fn of listeners) fn(snapshot)
}

/** Subscribe to preference changes; returns an unsubscribe function. */
export function subscribeEditorPrefs(fn: (prefs: EditorPrefs) => void): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}
