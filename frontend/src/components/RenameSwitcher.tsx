import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { validateVaultPath } from '../lib/paths'
import { pendingRenames } from '../lib/pending-rename'
import styles from './RenameSwitcher.module.css'

interface Props {
  open: boolean
  currentDocId: string
  /** Whether the file being renamed is a markdown note. Drives the endpoint
   *  choice (`/api/files/move` vs `/api/assets/move`) and the pending-rename
   *  WS suppression (only relevant for md, which lives in the CRDT layer). */
  currentIsMd: boolean
  onClose: () => void
}

export function RenameSwitcher({ open, currentDocId, currentIsMd, onClose }: Props) {
  const navigate = useNavigate()
  const [target, setTarget] = useState('')
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    if (!open) return
    setError(null)
    setTarget(currentDocId)
    queueMicrotask(() => {
      inputRef.current?.focus()
      inputRef.current?.select()
    })
  }, [open, currentDocId])

  async function commit(): Promise<void> {
    const dst = target.trim()
    if (!dst || dst === currentDocId) {
      onClose()
      return
    }
    const reason = validateVaultPath(dst)
    if (reason) {
      setError(reason)
      return
    }
    // Assets don't enter the CRDT layer — no in-memory doc, no WS to kick —
    // so the pending-rename suppression logic only matters for `.md` moves.
    const endpoint = currentIsMd ? '/api/files/move' : '/api/assets/move'
    if (currentIsMd) {
      // Mark the destination as expected BEFORE the request goes out, so the
      // server-initiated WS close (which can arrive concurrently with the HTTP
      // response) recognises us as the initiator and skips the "follow?" banner.
      pendingRenames.add(dst)
    }
    const r = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ src: currentDocId, dst }),
    })
    if (!r.ok) {
      if (currentIsMd) pendingRenames.delete(dst)
      const detail = await r.text()
      setError(`rename failed: ${r.status} ${detail}`)
      return
    }
    onClose()
    // Navigate directly to the new location — for `.md`, the close handler
    // will see the dst in pendingRenames and stay silent, so this is the only
    // navigation. For assets there's no close-event to race with.
    void navigate('/' + dst)
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>): void {
    if (e.key === 'Escape') onClose()
    else if (e.key === 'Enter') {
      e.preventDefault()
      void commit()
    }
  }

  if (!open) return null

  return (
    <div className={styles.backdrop} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          onKeyDown={onKeyDown}
          type="text"
          className={styles.input}
          placeholder="Rename to…"
          autoComplete="off"
          spellCheck={false}
        />
        <div className={styles.hint}>
          Renaming <code>{currentDocId}</code>
        </div>
        {error && <div className={styles.error}>{error}</div>}
      </div>
    </div>
  )
}
