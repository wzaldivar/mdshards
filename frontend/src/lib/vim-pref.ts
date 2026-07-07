/**
 * Vim-mode on/off preference.
 *
 * This is the ONE piece of persistent client storage in the app. CLAUDE.md's
 * "no persistent client storage" rule is about not shadowing vault/document
 * state on the client (no IndexedDB/PouchDB/etc.); a single editor UI
 * preference is a deliberate, documented exception — it never holds vault data
 * and its loss only reverts the editor to the default keymap.
 *
 * All access is wrapped so a `localStorage` that throws (private-mode quotas,
 * disabled storage) degrades to "vim off" rather than crashing the editor.
 */

const KEY = 'mdshards:vim'

export function isVimEnabled(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

export function setVimEnabled(on: boolean): void {
  try {
    localStorage.setItem(KEY, on ? '1' : '0')
  } catch {
    /* storage unavailable — preference just won't persist this session */
  }
}
