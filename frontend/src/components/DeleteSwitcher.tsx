import { backendUrl } from '../lib/backend'
import { NO_AUTOFILL } from '../lib/no-autofill'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { encodePathToUrl } from '../lib/paths'
import { fetchTree, flattenTree } from '../lib/tree'
import styles from './DeleteSwitcher.module.css'

interface Props {
  open: boolean
  currentDocId: string
  /** Whether the currently open file is a markdown note. Used both for the
   *  "Delete this file" top entry and for routing the DELETE to the right
   *  endpoint. A URL-pattern heuristic isn't enough anymore — dotty md
   *  filenames (`notes/my.weekly`) look like assets by URL alone. */
  currentIsMd: boolean
  onClose: () => void
}

interface Entry {
  label: string
  target: string
  /** Disk-path-derived: md files end in `.md`, assets keep their native
   *  extension. Used to dispatch to `/api/files/...` vs `/api/assets/...`. */
  isMd: boolean
}

export function DeleteSwitcher({ open, currentDocId, currentIsMd, onClose }: Props) {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  // Disk paths of every vault file, excluding `index.md`. Keeping the disk
  // form lets us derive isMd per entry; we strip the .md only for display.
  const [allFiles, setAllFiles] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [confirming, setConfirming] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    if (!open) return
    setError(null)
    setQuery('')
    setSelectedIndex(0)
    setConfirming(null)
    let cancelled = false
    void (async () => {
      try {
        const tree = await fetchTree()
        if (cancelled) return
        const all = flattenTree(tree, { filesOnly: true })
        // Exclude `index.md` — it's never deletable via UI.
        setAllFiles(all.filter((p) => p !== 'index.md'))
      } catch (e) {
        if (cancelled) return
        setError((e as Error).message)
      }
    })()
    queueMicrotask(() => inputRef.current?.focus())
    return () => {
      cancelled = true
    }
  }, [open])

  const entries = useMemo<Entry[]>(() => {
    const list: Entry[] = []
    if (currentDocId !== '' && currentDocId !== 'index') {
      list.push({
        label: `Delete this file (${currentDocId})`,
        target: currentDocId,
        isMd: currentIsMd,
      })
    }
    const q = query.trim().toLowerCase()
    for (const disk of allFiles) {
      const isMd = disk.endsWith('.md')
      const url = isMd ? disk.slice(0, -3) : disk
      // Current file is already the first entry; don't list it again below.
      if (url === currentDocId) continue
      if (q && !url.toLowerCase().includes(q)) continue
      list.push({ label: url, target: url, isMd })
    }
    // No display cap — every vault file stays reachable by arrows/scrolling.
    return list
  }, [query, allFiles, currentDocId, currentIsMd])

  // Withdraw an in-progress confirmation when the query moves — but ONLY
  // then. Keying this off `entries` too would cancel a confirmation the
  // moment the async tree fetch resolves and changes the memo's identity.
  useEffect(() => {
    setConfirming(null)
  }, [query])

  // Move the highlight to the first BEST match as the user types (exact
  // beats prefix beats substring — same ranking as the quick switcher),
  // instead of leaving it parked on the "Delete this file" top entry while
  // the user is clearly naming a different file. Falls back to the top row
  // on an empty or unmatched query.
  useEffect(() => {
    const q = query.trim().toLowerCase()
    if (!q) {
      setSelectedIndex(0)
      return
    }
    const forms = (e: Entry) => [e.target.toLowerCase(), e.label.toLowerCase()]
    const byExact = entries.findIndex((e) => forms(e).some((f) => f === q))
    const byPrefix = entries.findIndex((e) => forms(e).some((f) => f.startsWith(q)))
    const bySubstring = entries.findIndex((e) => forms(e).some((f) => f.includes(q)))
    const best = [byExact, byPrefix, bySubstring].find((i) => i !== -1)
    setSelectedIndex(best ?? 0)
  }, [query, entries])

  async function doDelete(entry: Entry): Promise<void> {
    if (entry.target === '' || entry.target === 'index') {
      setError("index can't be deleted")
      return
    }
    // Capture whether we're deleting the open file BEFORE the await. Deleting
    // an md file kicks its WebSocket, and the Editor's close handler navigates
    // to '/' (flipping currentDocId to '') while this request is in flight — so
    // reading currentDocId afterwards can miss. More importantly, that WS-close
    // navigation doesn't happen on Safari at all: WebKit doesn't surface our
    // application close code (4001), reporting 1006 instead, so the Editor's
    // `code === DOC_DELETED_CODE` branch never fires. Making this fetch-success
    // path the source of truth navigates reliably regardless of the socket.
    const wasCurrent = entry.target === currentDocId
    const endpoint = entry.isMd ? '/api/files/' : '/api/assets/'
    const r = await fetch(backendUrl(endpoint + encodePathToUrl(entry.target)), { method: 'DELETE' })
    if (!r.ok) {
      setError(`delete failed: ${r.status}`)
      return
    }
    onClose()
    if (wasCurrent) void navigate('/')
  }

  function selectAndConfirm(i: number): void {
    setSelectedIndex(i)
    const entry = entries[i]
    if (!entry) return
    if (confirming === entry.target) {
      void doDelete(entry)
    } else {
      setConfirming(entry.target)
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>): void {
    if (e.key === 'Escape') {
      onClose()
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex((i) => Math.min(entries.length - 1, i + 1))
      setConfirming(null)
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex((i) => Math.max(0, i - 1))
      setConfirming(null)
      return
    }
    if (e.key === 'Enter') {
      e.preventDefault()
      const entry = entries[selectedIndex]
      if (!entry) return
      if (confirming === entry.target) {
        void doDelete(entry)
      } else {
        setConfirming(entry.target)
      }
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
          placeholder="Pick a file to delete…"
          {...NO_AUTOFILL}
        />
        <ul className={styles.list}>
          {entries.map((entry, i) => {
            const classes = [styles.item]
            if (i === selectedIndex) classes.push(styles.itemSelected)
            if (confirming === entry.target) classes.push(styles.itemConfirming)
            return (
              <li
                key={entry.label}
                // Keep the keyboard selection visible when the list scrolls:
                // the ref fires as the item becomes selected; 'nearest' makes
                // it a no-op while it's already in view.
                ref={i === selectedIndex ? (el) => el?.scrollIntoView({ block: 'nearest' }) : undefined}
                className={classes.join(' ')}
                onClick={() => selectAndConfirm(i)}
              >
                {confirming === entry.target ? (
                  <span>Confirm delete: {entry.label} (Enter)</span>
                ) : (
                  <span>{entry.label}</span>
                )}
              </li>
            )
          })}
        </ul>
        {error && <div className={styles.error}>{error}</div>}
      </div>
    </div>
  )
}
