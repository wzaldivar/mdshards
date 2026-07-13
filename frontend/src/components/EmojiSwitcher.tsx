import { useEffect, useMemo, useRef, useState } from 'react'
import { getGemojiList, loadEmojiData, type GemojiEntry } from '../lib/emoji'
import styles from './QuickSwitcher.module.css'

interface Props {
  open: boolean
  /** Called with the picked shortcode NAME (no colons); the parent inserts
   *  `:name:` into the buffer. The file keeps the shortcode — the glyph is
   *  render-time only (markdown-live's Emoji handling). */
  onPick: (name: string) => void
  onClose: () => void
}

/** Cmd-E emoji picker. Same modal/list chrome as the quick switcher, backed
 *  by the lazily-loaded gemoji dataset (lib/emoji.ts). Rows show the glyph
 *  plus its primary `:name:`; matching covers every alias and the prose
 *  description (`magnifying` finds `:mag:`). */
export function EmojiSwitcher({ open, onPick, onClose }: Props) {
  const [query, setQuery] = useState('')
  const [entries, setEntries] = useState<GemojiEntry[] | null>(getGemojiList())
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    if (!open) return
    setQuery('')
    setSelectedIndex(0)
    let cancelled = false
    void loadEmojiData().then(() => {
      if (!cancelled) setEntries(getGemojiList())
    })
    queueMicrotask(() => inputRef.current?.focus())
    return () => {
      cancelled = true
    }
  }, [open])

  const matches = useMemo(() => {
    if (!entries) return []
    const q = query.trim().toLowerCase()
    // No display cap, unlike the file switchers: an emoji picker is also a
    // BROWSING tool — the whole dataset stays reachable by arrows/scrolling
    // even with an empty query. ~2k plain rows render fine.
    if (!q) return entries
    const nameHit = (e: GemojiEntry) => e.names.some((n) => n.includes(q))
    const descHit = (e: GemojiEntry) => e.description.toLowerCase().includes(q)
    // Names outrank descriptions; exact name outranks both.
    const exact = entries.filter((e) => e.names.includes(q))
    const byName = entries.filter((e) => !e.names.includes(q) && nameHit(e))
    const byDesc = entries.filter((e) => !nameHit(e) && descHit(e))
    return [...exact, ...byName, ...byDesc]
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
    <div className={styles.backdrop} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          type="text"
          className={styles.input}
          placeholder="Insert emoji…"
          autoComplete="off"
          spellCheck={false}
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
                className={`${styles.item} ${i === selectedIndex ? styles.itemSelected : ''}`}
                onClick={() => pick(i)}
              >
                {entry.emoji} :{entry.names[0]}:
              </li>
            ))
          )}
        </ul>
      </div>
    </div>
  )
}
