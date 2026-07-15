/**
 * Global keybindings for the editor:
 *   - Cmd/Ctrl-K          → quick switcher (go-to / create)
 *   - Cmd/Ctrl-Shift-K    → rename current file
 *   - Cmd/Ctrl-Backspace  → delete switcher
 *   - Cmd/Ctrl-U          → open the file picker (uploads disabled in demo)
 *   - Cmd/Ctrl-E          → emoji picker (inserts `:shortcode:` at cursor)
 *   - Cmd/Ctrl-Alt-O      → editor options panel (vim / line numbers)
 *
 * Each binding overrides both the browser default and any CodeMirror keymap
 * via `preventDefault` + `stopPropagation`. Registered in the capture phase
 * so we win the race against CM6's listener (which is attached to the
 * editor's contenteditable, deeper in the DOM tree).
 *
 * Modifier matching is strict — Alt participates ONLY for the options panel
 * (Cmd/Ctrl-Alt-O); every other binding requires Alt to be up. Shift only
 * when the binding explicitly opts in.
 *
 * Key detection prefers `e.code` so non-Latin / dead-key layouts still match.
 *
 * `bindShortcuts(target, …)` attaches to any EventTarget so the AssetViewer
 * can re-attach the handler inside its iframe's contentDocument — without
 * that, focusing the iframe (clicking on an image / PDF) would steal keydown
 * events and the shortcuts would silently stop working.
 */

export interface ShortcutHandlers {
  openQuickSwitcher: () => void
  openDeleteSwitcher: () => void
  openRenameSwitcher: () => void
  openUploadSwitcher: () => void
  openEmojiPicker: () => void
  openOptions: () => void
}

function isLetter(e: KeyboardEvent, code: string, letter: string): boolean {
  return e.code === code || e.key.toLowerCase() === letter
}

function buildListener(handlers: ShortcutHandlers): (e: KeyboardEvent) => void {
  return (e) => {
    const cmd = e.metaKey || e.ctrlKey
    if (!cmd) return

    // The options panel is the one Alt-using binding; handle it first, then
    // bail on any other Alt combo so those still pass through to the OS / CM.
    if (e.altKey) {
      if (isLetter(e, 'KeyO', 'o') && !e.shiftKey) {
        e.preventDefault()
        e.stopPropagation()
        handlers.openOptions()
      }
      return
    }

    let handler: (() => void) | null = null
    if (isLetter(e, 'KeyK', 'k')) {
      handler = e.shiftKey ? handlers.openRenameSwitcher : handlers.openQuickSwitcher
    } else if (e.code === 'Backspace' && !e.shiftKey) {
      handler = handlers.openDeleteSwitcher
    } else if (isLetter(e, 'KeyU', 'u') && !e.shiftKey) {
      handler = handlers.openUploadSwitcher
    } else if (isLetter(e, 'KeyE', 'e') && !e.shiftKey) {
      handler = handlers.openEmojiPicker
    }

    if (handler) {
      e.preventDefault()
      e.stopPropagation()
      handler()
    }
  }
}

export function bindShortcuts(target: EventTarget, handlers: ShortcutHandlers): () => void {
  const onKey = buildListener(handlers) as EventListener
  // Capture phase so we beat CodeMirror's own keydown listener as well as
  // anything inside an iframe (e.g. an image viewer).
  target.addEventListener('keydown', onKey, true)
  return () => target.removeEventListener('keydown', onKey, true)
}

export function bindGlobalShortcuts(handlers: ShortcutHandlers): () => void {
  return bindShortcuts(window, handlers)
}
