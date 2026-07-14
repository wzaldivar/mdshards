import { backendUrl } from '../lib/backend'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { encodePathToUrl, validateVaultPath } from '../lib/paths'
import { pendingRenames } from '../lib/pending-rename'
import { SwitcherShell } from './SwitcherShell'
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

export function RenameSwitcher({ open, currentDocId, currentIsMd, onClose }: Readonly<Props>) {
  const navigate = useNavigate()
  const [target, setTarget] = useState('')
  const [error, setError] = useState<string | null>(null)
  // Set once the user has been told that renaming this asset to a `.md`
  // target converts it into a note; the next Enter on the unchanged target
  // is the confirmation. Editing the target withdraws it.
  const [confirmingConvert, setConfirmingConvert] = useState(false)
  const inputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    if (!open) return
    setError(null)
    setConfirmingConvert(false)
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
    // Renaming an asset to a `.md` target (any casing) converts it into a
    // note — meaningful enough to require a second Enter. Whether the bytes
    // make sense as markdown is the user's call.
    const convertsToNote = !currentIsMd && dst.slice(-3).toLowerCase() === '.md'
    if (convertsToNote && !confirmingConvert) {
      setConfirmingConvert(true)
      setError(
        `this will transform the asset into the note "${dst.slice(0, -3)}" — press Enter again to confirm`,
      )
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
    const r = await fetch(backendUrl(endpoint), {
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
    // navigation. For assets there's no close-event to race with. A
    // conversion's canonical URL is the doc-id the backend returns.
    const body = (await r.json().catch(() => null)) as { to?: string; converted?: boolean } | null
    const destination = body?.converted && body.to ? body.to : dst
    navigate('/' + encodePathToUrl(destination))
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
    <SwitcherShell
      inputRef={inputRef}
      value={target}
      onChange={(e) => {
        setTarget(e.target.value)
        // Editing the target withdraws a pending convert confirmation.
        if (confirmingConvert) {
          setConfirmingConvert(false)
          setError(null)
        }
      }}
      onKeyDown={onKeyDown}
      placeholder="Rename to…"
      onClose={onClose}
    >
      <div className={styles.hint}>
        Renaming <code>{currentDocId}</code>
      </div>
      {error && <div className={styles.error}>{error}</div>}
    </SwitcherShell>
  )
}
