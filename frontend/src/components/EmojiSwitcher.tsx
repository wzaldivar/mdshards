import { useEffect, useMemo, useRef, useState } from 'react'
import { getGemojiList, loadEmojiData, type GemojiEntry } from '../lib/emoji'
import { useListNavigation } from '../lib/use-list-navigation'
import { SwitcherShell } from './SwitcherShell'
import styles from './QuickSwitcher.module.css'

interface Props {
  open: boolean
  /** Seed query — the shortcode token the cursor was touching when the
   *  picker opened (`:smi` → "smi"), so a half-typed or wrong emoji can be
   *  finished/replaced without retyping. Empty for a plain open. */
  initialQuery: string
  /** Called with the picked entry's shortcode NAME (no colons) and its glyph.
   *  `asGlyph` picks the write mode: Enter (false) writes `:name:` — the file
   *  keeps the shortcode, the glyph is render-time only; Shift-Enter (true)
   *  writes the literal `glyph` straight into the buffer as a plain character.
   *  Either way the touched token (if any) is replaced. */
  onPick: (name: string, glyph: string, asGlyph: boolean) => void
  onClose: () => void
}

/** Cmd-E emoji picker. Same modal/list chrome as the quick switcher, backed
 *  by the lazily-loaded gemoji dataset (lib/emoji.ts). Rows show the glyph
 *  plus its primary `:name:`; matching covers every alias and the prose
 *  description (`magnifying` finds `:mag:`). */
export function EmojiSwitcher({ open, initialQuery, onPick, onClose }: Readonly<Props>) {
  const [query, setQuery] = useState('')
  const [entries, setEntries] = useState<GemojiEntry[] | null>(getGemojiList())
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
    // Shortest matching-name length, hoisted out of the sort callback so the
    // filter/map below aren't nested >4 functions deep (S2004).
    const shortestPrefixLen = (e: GemojiEntry): number =>
      Math.min(...e.names.filter((n) => n.startsWith(q)).map((n) => n.length))
    const exact = entries.filter((e) => e.names.includes(q))
    const byPrefix = entries
      .filter((e) => !e.names.includes(q) && prefixHit(e))
      .sort((a, b) => shortestPrefixLen(a) - shortestPrefixLen(b))
    const bySubstring = entries.filter((e) => !prefixHit(e) && nameHit(e))
    const byDesc = entries.filter((e) => !nameHit(e) && descHit(e))
    return [...exact, ...byPrefix, ...bySubstring, ...byDesc]
  }, [entries, query])

  // `e` is present for Enter (from useListNavigation) and absent for a mouse
  // click; Shift-Enter writes the glyph, plain Enter / click writes `:name:`.
  function pick(i: number, e?: React.KeyboardEvent<HTMLInputElement>): void {
    const entry = matches[i]
    if (!entry) return
    onPick(entry.names[0], entry.emoji, e?.shiftKey ?? false)
    onClose()
  }

  const { selectedIndex, setSelectedIndex, onKeyDown } = useListNavigation({
    count: matches.length,
    onClose,
    onEnter: pick,
  })

  useEffect(() => {
    setSelectedIndex(0)
  }, [query, setSelectedIndex])

  if (!open) return null

  return (
    <SwitcherShell
      inputRef={inputRef}
      value={query}
      onChange={(e) => setQuery(e.target.value)}
      onKeyDown={onKeyDown}
      placeholder="Insert emoji…"
      onClose={onClose}
    >
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
      <div className={`${styles.item} ${styles.createHint}`}>
        <span>
          <span className={styles.kbd}>Enter</span> :code:
        </span>
        <span>
          <span className={styles.kbd}>Shift-Enter</span> glyph
        </span>
      </div>
    </SwitcherShell>
  )
}
