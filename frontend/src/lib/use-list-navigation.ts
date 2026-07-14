import { useState } from 'react'

interface Options {
  /** Number of selectable rows — the upper clamp for ArrowDown. */
  count: number
  onClose: () => void
  /** Enter on the highlighted row. Receives the current index and the raw
   *  event, so callers can branch on modifiers (the quick switcher keys
   *  create off `shiftKey`). */
  onEnter: (index: number, e: React.KeyboardEvent<HTMLInputElement>) => void
  /** Ran after an arrow key moves the highlight — the delete switcher uses it
   *  to withdraw a pending delete confirmation. */
  onMove?: () => void
}

/** The keyboard contract shared by the list-based switchers (quick / delete /
 *  emoji): Escape closes, ArrowUp/Down move a clamped highlight, Enter acts on
 *  the highlighted row. Owns the `selectedIndex` state so callers can still
 *  drive it directly (e.g. jump-to-best-match effects) via the returned
 *  setter. Single-field switchers (rename / upload) don't use this. */
export function useListNavigation({ count, onClose, onEnter, onMove }: Options) {
  const [selectedIndex, setSelectedIndex] = useState(0)

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>): void {
    if (e.key === 'Escape') {
      onClose()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex((i) => Math.min(count - 1, i + 1))
      onMove?.()
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex((i) => Math.max(0, i - 1))
      onMove?.()
    } else if (e.key === 'Enter') {
      e.preventDefault()
      onEnter(selectedIndex, e)
    }
  }

  return { selectedIndex, setSelectedIndex, onKeyDown }
}
