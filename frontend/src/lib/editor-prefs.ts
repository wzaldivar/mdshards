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
 * either side reaching into the other. Changes also propagate across tabs: the
 * browser fires a `storage` event in every *other* tab when localStorage
 * changes, which we fan out to the same subscribers so all open tabs re-apply
 * in lockstep.
 */

import { isTouchPrimary, subscribeTouchPrimary } from './touch'

export interface EditorPrefs {
  vim: boolean
  lineNumbers: boolean
  relativeLineNumbers: boolean
  centerLine: boolean
}

const KEYS: Record<keyof EditorPrefs, string> = {
  vim: 'mdshards:vim',
  lineNumbers: 'mdshards:lineNumbers',
  relativeLineNumbers: 'mdshards:relativeLineNumbers',
  centerLine: 'mdshards:centerLine',
}

function read(key: string): boolean {
  try {
    return localStorage.getItem(key) === '1'
  } catch {
    return false
  }
}

/**
 * The user's preferences as they'll actually be applied.
 *
 * Two prefs are clamped off on a keyboardless touch device (see `lib/touch.ts`)
 * because they presuppose a desktop:
 *   - `vim` — modal editing needs Escape, `:`, and hjkl, none of which a
 *     software keyboard offers, and a buffer stuck in NORMAL swallows every
 *     keystroke, so the editor just looks broken.
 *   - `centerLine` — typewriter scrolling centers within the CodeMirror
 *     scroller, which is sized by the LAYOUT viewport; the software keyboard
 *     only shrinks the VISUAL one. So the "centered" line lands under the
 *     keyboard, and re-centering on every tap fights the browser's own caret
 *     scrolling. On a phone-sized screen it costs vertical space and yanks the
 *     viewport around for no benefit (user call, 2026-09-07).
 *
 * Both clamps are applied on READ, never by writing storage, so the stored
 * choice survives: the same browser profile on a desktop (or a tablet docked to
 * a keyboard) gets both back.
 */
export function getEditorPrefs(): EditorPrefs {
  const touch = isTouchPrimary()
  return {
    vim: read(KEYS.vim) && !touch,
    lineNumbers: read(KEYS.lineNumbers),
    relativeLineNumbers: read(KEYS.relativeLineNumbers),
    centerLine: read(KEYS.centerLine) && !touch,
  }
}

const listeners = new Set<(prefs: EditorPrefs) => void>()

function notify(): void {
  const snapshot = getEditorPrefs()
  for (const fn of listeners) fn(snapshot)
}

export function setEditorPref(key: keyof EditorPrefs, on: boolean): void {
  try {
    localStorage.setItem(KEYS[key], on ? '1' : '0')
  } catch {
    /* storage unavailable — preference just won't persist this session */
  }
  notify()
}

/** Subscribe to preference changes; returns an unsubscribe function. */
export function subscribeEditorPrefs(fn: (prefs: EditorPrefs) => void): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

// Cross-tab propagation: a `storage` event fires in every OTHER tab when one of
// our keys changes (the originating tab is covered by `setEditorPref` above).
// `e.key` is null when storage is cleared wholesale — re-read and fan out then
// too. Guarded for non-browser (test/SSR) contexts.
if (typeof window !== 'undefined') {
  const ownKeys = new Set<string>(Object.values(KEYS))
  window.addEventListener('storage', (e: StorageEvent) => {
    if (e.key === null || ownKeys.has(e.key)) notify()
  })
  // The clamps above are a function of the pointer capability, so a change in
  // it changes the effective prefs even though storage didn't move. Fan it out
  // on the same channel so the live editor reconfigures its vim / centre-line
  // compartments (e.g. a tablet docked to / undocked from a keyboard case).
  subscribeTouchPrimary(notify)
}
