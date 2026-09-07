/**
 * Touch-environment detection — "is this a keyboardless touch device?".
 *
 * The app is keyboard-first (see `shortcuts.ts`): every vault operation hangs
 * off a Cmd/Ctrl chord. On a phone or tablet there is no chord to press, so
 * those surfaces are unreachable and vim mode is unusable. This module is the
 * single place that decides when to swap in the touch affordances (the
 * `TouchBar`) and drop the ones that presuppose a keyboard (vim).
 *
 * The signal is `(pointer: coarse) and (hover: none)` — the *primary* pointer
 * is a finger and it can't hover. Both halves matter:
 *   - `pointer: coarse` alone also matches a desktop with a touchscreen, where
 *     the keyboard is right there and vim should stay available.
 *   - `hover: none` alone matches some kiosk/stylus setups.
 * Together they mean phone/tablet, which is exactly the keyboardless case.
 *
 * Deliberately NOT sniffing `navigator.userAgent` or `ontouchstart` — the media
 * query is the standard capability signal, tracks devtools device emulation,
 * and re-evaluates live when a tablet gains a keyboard case (the `change`
 * event below fans that out to subscribers).
 */

import { useEffect, useState } from 'react'

const TOUCH_QUERY = '(pointer: coarse) and (hover: none)'

/** The MediaQueryList, or null in a non-browser / jsdom context where
 *  `matchMedia` isn't implemented. Resolved lazily so tests can stub
 *  `window.matchMedia` before the first call. */
function mediaQuery(): MediaQueryList | null {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return null
  }
  try {
    return window.matchMedia(TOUCH_QUERY)
  } catch {
    // A stub that doesn't understand the query string — treat as desktop.
    return null
  }
}

/**
 * True when the primary pointer is a finger and there's no hover — i.e. a
 * phone/tablet with no physical keyboard. False everywhere `matchMedia` is
 * unavailable (tests, SSR), so the desktop keyboard-first behavior is the
 * safe default.
 */
export function isTouchPrimary(): boolean {
  return mediaQuery()?.matches ?? false
}

/**
 * Subscribe to changes in touch-primaryness; returns an unsubscribe function.
 * Fires when a tablet is docked to a keyboard, on orientation/device-emulation
 * changes, etc. A no-op unsubscribe when `matchMedia` is unavailable.
 */
export function subscribeTouchPrimary(fn: (touch: boolean) => void): () => void {
  const mql = mediaQuery()
  if (!mql) return () => {}
  const onChange = (e: MediaQueryListEvent): void => fn(e.matches)
  mql.addEventListener('change', onChange)
  return () => mql.removeEventListener('change', onChange)
}

/** React binding for {@link isTouchPrimary}, kept live via the media-query
 *  `change` event so the UI re-renders if the capability flips. */
export function useTouchPrimary(): boolean {
  const [touch, setTouch] = useState(isTouchPrimary)
  useEffect(() => {
    // Re-read on mount: the first render may have run before a device-emulation
    // toggle, and this also covers the lazy-`matchMedia` case above.
    setTouch(isTouchPrimary())
    return subscribeTouchPrimary(setTouch)
  }, [])
  return touch
}
