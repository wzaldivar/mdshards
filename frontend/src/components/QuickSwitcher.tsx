import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { getHomePath } from '../lib/config'
import { diskPathToUrl, fetchTree, flattenTree } from '../lib/tree'
import { validateVaultPath } from '../lib/paths'
import styles from './QuickSwitcher.module.css'

interface Props {
  open: boolean
  currentDocId: string
  onClose: () => void
}

/** How a doc-id is shown in the picker: the URL it actually lives at. The
 * home note (`index.md`, doc-id `index`) shows as the app root; others show
 * by doc-id. When the app is deployed at a sub-path (`homePath` e.g.
 * `/wiki`), every row is qualified with that prefix so the picker reflects
 * where navigation will land (`/wiki/`, `/wiki/foo`). At root `homePath` is
 * `''` and rows stay bare (`/`, `foo`). This is display only — navigation
 * still targets the bare vault path and lets React Router's basename apply
 * the prefix (double-prefixing would produce `/wiki/wiki/foo`). */
function displayPath(p: string): string {
  const base = getHomePath()
  if (p === 'index') return base ? `${base}/` : '/'
  return base ? `${base}/${p}` : p
}

export function QuickSwitcher({ open, currentDocId, onClose }: Props) {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [allPaths, setAllPaths] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    if (!open) return
    setError(null)
    setQuery('')
    setSelectedIndex(0)
    let cancelled = false
    void (async () => {
      try {
        const tree = await fetchTree()
        if (cancelled) return
        setAllPaths(flattenTree(tree, { filesOnly: true }))
      } catch (e) {
        if (cancelled) return
        setError((e as Error).message)
      }
    })()
    // Focus on the next paint, after the input has been mounted.
    queueMicrotask(() => inputRef.current?.focus())
    return () => {
      cancelled = true
    }
  }, [open])

  // Reset highlight when the query changes.
  useEffect(() => {
    setSelectedIndex(0)
  }, [query])

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase()
    const urls = allPaths.map(diskPathToUrl)
    // The current file is "already open" — picking it would do nothing useful.
    const currentTarget = currentDocId === '' ? 'index' : currentDocId

    // Pull `index` out separately so we can always pin it to the top.
    const others = urls
      .filter((p) => p !== currentTarget && p !== 'index')
      .filter(
        (p) => !q || p.toLowerCase().includes(q) || displayPath(p).toLowerCase().includes(q),
      )

    const list: string[] = []
    // `/` is always the first option unless the user is already on home.
    if (currentTarget !== 'index') list.push('index')
    list.push(...others)
    return list.slice(0, 50)
  }, [query, allPaths, currentDocId])

  const hasExactMatch = useMemo(() => {
    const q = query.trim()
    return matches.some((p) => p === q || displayPath(p) === q)
  }, [matches, query])

  async function commit(target: string, forceCreate = false): Promise<void> {
    if (!target) return
    if (!forceCreate && allPaths.map(diskPathToUrl).includes(target)) {
      // Keep the URL bar clean: `/index` would resolve to the same file but the
      // canonical home URL is just `/`.
      void navigate(target === 'index' ? '/' : '/' + target)
      onClose()
      return
    }
    const reason = validateVaultPath(target)
    if (reason) {
      setError(reason)
      return
    }
    const r = await fetch('/api/files', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: target }),
    })
    if (!r.ok) {
      // 409 is the most likely failure when forceCreate is on and the typed
      // text turned out to be a real existing path; the message says enough.
      setError(`create failed: ${r.status}`)
      return
    }
    void navigate('/' + target)
    onClose()
  }

  function selectAndCommit(i: number): void {
    setSelectedIndex(i)
    const target = matches[i]
    if (target) void commit(target)
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
      if (e.shiftKey) {
        // Shift-Enter is the ONLY way to create. Force-create at the typed
        // text, ignoring whichever existing match is currently highlighted.
        void commit(query.trim(), true)
      } else {
        // Plain Enter navigates to an existing match only — it never creates.
        // When the query matches nothing there's no target, so it's a no-op
        // and the user must press Shift-Enter to create.
        const target = matches[selectedIndex]
        if (target) void commit(target)
      }
    }
  }

  if (!open) return null

  const trimmed = query.trim()
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
          placeholder="Go to or create a note…"
          autoComplete="off"
          spellCheck={false}
        />
        <ul className={styles.list}>
          {matches.map((p, i) => (
            <li
              key={p}
              className={`${styles.item} ${i === selectedIndex ? styles.itemSelected : ''}`}
              onClick={() => selectAndCommit(i)}
            >
              {displayPath(p)}
            </li>
          ))}
          {trimmed && !hasExactMatch && (
            <li className={`${styles.item} ${styles.createHint}`}>
              Create &ldquo;{trimmed}&rdquo;
              <span className={styles.kbd}> Shift-Enter</span>
            </li>
          )}
        </ul>
        {error && <div className={styles.error}>{error}</div>}
      </div>
    </div>
  )
}
