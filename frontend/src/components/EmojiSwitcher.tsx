import { useEffect, useMemo, useRef, useState } from 'react'
import { NO_AUTOFILL } from '../lib/no-autofill'
import { getGemojiList, loadEmojiData, type GemojiEntry } from '../lib/emoji'
import styles from './QuickSwitcher.module.css'

interface Props {
  open: boolean
  /** Seed query — the shortcode token the cursor was touching when the
   *  picker opened (`:smi` → "smi"), so a half-typed or wrong emoji can be
   *  finished/replaced without retyping. Empty for a plain open. */
  initialQuery: string
  /** Called with the picked shortcode NAME (no colons); the parent writes
   *  `:name:` into the buffer (replacing the touched token, if any). The
   *  file keeps the shortcode — the glyph is render-time only. */
  onPick: (name: string) => void
  onClose: () => void
}

/** Cmd-E emoji picker. Same modal/list chrome as the quick switcher, backed
 *  by the lazily-loaded gemoji dataset (lib/emoji.ts). Rows show the glyph
 *  plus its primary `:name:`; matching covers every alias and the prose
 *  description (`magnifying` finds `:mag:`). */
export function EmojiSwitcher({ open, initialQuery, onPick, onClose }: Props) {
  const [query, setQuery] = useState('')
  const [entries, setEntries] = useState<GemojiEntry[] | null>(getGemojiList())
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement | null>(null)

  // Arms on open when there's a seed; the select must happen AFTER the
  // render that commits the seeded value into the input (a microtask can
  // beat that commit and select stale text, making typing append instead of
  // replace) — hence the separate effect below keyed on `query`.
  const pendingSelect = useRef(false)

  useEffect(() => {
    if (!open) return
    setQuery(initialQuery)
    setSelectedIndex(0)
    pendingSelect.current = initialQuery.length > 0
    let cancelled = false
    void loadEmojiData().then(() => {
      if (!cancelled) setEntries(getGemojiList())
    })
    queueMicrotask(() => inputRef.current?.focus())
    return () => {
      cancelled = true
    }
  }, [open, initialQuery])

  useEffect(() => {
    if (!open || !pendingSelect.current) return
    const input = inputRef.current
    // Compare against the SEED, not the live query: on a reopen the first
    // commit still shows the previous session's query, and selecting that
    // stale text would burn the one-shot flag before the seed ever renders.
    if (input && initialQuery && input.value === initialQuery) {
      // Select the seeded token so typing a different name replaces it
      // outright, while Enter still takes the best match for the seed.
      input.focus()
      input.select()
      pendingSelect.current = false
    }
  }, [open, query, initialQuery])

  const matches = useMemo(() => {
    if (!entries) return []
    const q = query.trim().toLowerCase()
    // No display cap, unlike the file switchers: an emoji picker is also a
    // BROWSING tool — the whole dataset stays reachable by arrows/scrolling
    // even with an empty query. ~2k plain rows render fine.
    if (!q) return entries
    const nameHit = (e: GemojiEntry) => e.names.some((n) => n.includes(q))
    const prefixHit = (e: GemojiEntry) => e.names.some((n) => n.startsWith(q))
    const descHit = (e: GemojiEntry) => e.description.toLowerCase().includes(q)
    // Rank: exact name > name prefix (shortest completion first, so `smi`
    // offers :smile: before :smiley:) > name substring > description.
    const exact = entries.filter((e) => e.names.includes(q))
    const byPrefix = entries
      .filter((e) => !e.names.includes(q) && prefixHit(e))
      .sort((a, b) => {
        const len = (e: GemojiEntry) =>
          Math.min(...e.names.filter((n) => n.startsWith(q)).map((n) => n.length))
        return len(a) - len(b)
      })
    const bySubstring = entries.filter((e) => !prefixHit(e) && nameHit(e))
    const byDesc = entries.filter((e) => !nameHit(e) && descHit(e))
    return [...exact, ...byPrefix, ...bySubstring, ...byDesc]
  }, [entries, query])

  useEffect(() => {
    setSelectedIndex(0)
  }, [query])

  function pick(i: number): void {
    const entry = matches[i]
    if (!entry) return
    onPick(entry.names[0])
    onClose()
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>): void {
    if (e.key === 'Escape') {
      onClose()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex((i) => Math.min(matches.length - 1, i + 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex((i) => Math.max(0, i - 1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      pick(selectedIndex)
    }
  }

  if (!open) return null

  return (
    <div className={styles.backdrop}>
      {/* Native <button> close-catcher; see QuickSwitcher for the rationale. */}
      <button type="button" className={styles.scrim} aria-label="Close" tabIndex={-1} onClick={onClose} />
      <div className={styles.modal}>
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          type="text"
          className={styles.input}
          placeholder="Insert emoji…"
          {...NO_AUTOFILL}
        />
        <ul className={styles.list}>
          {entries === null ? (
            <li className={styles.item}>Loading emoji…</li>
          ) : (
            matches.map((entry, i) => (
              <li
                key={entry.names[0]}
                // Keep the keyboard selection visible when the list scrolls.
                ref={i === selectedIndex ? (el) => el?.scrollIntoView({ block: 'nearest' }) : undefined}
              >
                <button
                  type="button"
                  className={`${styles.item} ${i === selectedIndex ? styles.itemSelected : ''}`}
                  tabIndex={-1}
                  onClick={() => pick(i)}
                >
                  {entry.emoji} :{entry.names[0]}:
                </button>
              </li>
            ))
          )}
        </ul>
      </div>
    </div>
  )
}
