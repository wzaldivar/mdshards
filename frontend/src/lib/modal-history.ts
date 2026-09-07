/**
 * Back-button dismissal for the modal switchers.
 *
 * On a phone, Back is the universal "dismiss" gesture — but a modal here is
 * React state, not a route, so Back would sail past it and navigate away from
 * the note instead. The fix is a **sentinel history entry**: pushed when a
 * modal opens, it gives Back something to pop. The `popstate` that results
 * closes the modal and the URL is right back where it started, so nothing
 * navigates.
 *
 * The entry carries no URL of its own — `pushState(state, '')` keeps the
 * current one — so React Router re-renders the same route either way and the
 * user never sees the address change.
 *
 * Closing by any OTHER route (Escape, the scrim, committing) has to remove the
 * sentinel again, or the next Back would be swallowed by a leftover entry and
 * appear to do nothing. `consumeModalSentinel` handles that, and is a no-op
 * when `popstate` already consumed it — so both close paths converge on a
 * clean history.
 *
 * The one case that needs care is a modal that commits by NAVIGATING (the
 * quick switcher opening a note, delete going home, rename following the
 * move). There the sentinel is buried under the new entry and can no longer be
 * popped, which would cost the user a dead Back press. Those call sites pass
 * `replace: hasModalSentinel()` to `navigate`, overwriting the sentinel rather
 * than stacking on top of it — see `QuickSwitcher.commit`.
 *
 * Deliberately NOT React-Router history: this is browser-level session
 * history, and the sentinel must be invisible to the router's own routing.
 */

/** Marker on `history.state` identifying an entry we pushed. */
const SENTINEL_KEY = 'mdshardsModal'

function historyState(): Record<string, unknown> | null {
  if (typeof window === 'undefined') return null
  return (window.history.state ?? null) as Record<string, unknown> | null
}

/** True when the CURRENT history entry is one we pushed for an open modal. */
export function hasModalSentinel(): boolean {
  return historyState()?.[SENTINEL_KEY] === true
}

/** Push the sentinel, giving the Back button something to pop. Keeps the
 *  current URL — only the history depth changes. */
export function pushModalSentinel(): void {
  if (typeof window === 'undefined') return
  // Never stack two: a modal-to-modal switch (closeAll + open another) must
  // stay one Back press away from dismissed.
  if (hasModalSentinel()) return
  window.history.pushState({ [SENTINEL_KEY]: true }, '')
}

/** Remove the sentinel if it's still the current entry — the close-by-other-
 *  means path. No-op once `popstate` has already consumed it, and no-op when a
 *  navigation replaced//buried it, so it can never eat a real history entry. */
export function consumeModalSentinel(): void {
  if (typeof window === 'undefined') return
  if (hasModalSentinel()) window.history.back()
}
