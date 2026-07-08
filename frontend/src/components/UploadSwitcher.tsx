import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { encodePathToUrl, validateVaultPath } from '../lib/paths'
import { finalizeUploadPath } from '../lib/upload-path'
import styles from './UploadSwitcher.module.css'

interface Props {
  open: boolean
  currentDocId: string
  /** The file the user already picked via the system file dialog (Cmd-U
   *  triggers the picker BEFORE this modal opens, so a file is virtually
   *  always present). Null is allowed only so the parent can render the
   *  switcher without a file in edge cases. */
  initialFile: File | null
  onClose: () => void
}

export function UploadSwitcher({ open, currentDocId, initialFile, onClose }: Props) {
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [target, setTarget] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  /** What we'd actually upload at if the user submitted right now — used as a
   * live preview under the input so the extension rules are obvious. */
  const previewPath = useMemo<string | null>(() => {
    if (!file || !target.trim()) return null
    return finalizeUploadPath(target, file.name)
  }, [file, target])

  useEffect(() => {
    if (!open) return
    setError(null)
    setBusy(false)
    setFile(initialFile)
    // Prefill the target as `<current dir>/<filename>` so the user can press
    // Enter to confirm the obvious case. Spaces are kept verbatim — vault
    // paths allow them (they're percent-encoded only at the URL boundary).
    const dir = currentDocId.includes('/')
      ? currentDocId.slice(0, currentDocId.lastIndexOf('/') + 1)
      : ''
    const base = initialFile ? initialFile.name : ''
    setTarget(dir + base)
    queueMicrotask(() => {
      inputRef.current?.focus()
      // Select the prefilled path so the user can immediately retype if they
      // don't want the defaulted name. Cursor lands at the end otherwise.
      inputRef.current?.select()
    })
  }, [open, currentDocId, initialFile])

  function pickFile(): void {
    fileInputRef.current?.click()
  }

  function onFileChange(e: React.ChangeEvent<HTMLInputElement>): void {
    setFile(e.target.files?.[0] ?? null)
  }

  async function commit(): Promise<void> {
    if (!file) {
      setError('pick a file first')
      return
    }
    const resolved = finalizeUploadPath(target, file.name)
    if (!resolved) {
      setError('enter a target path')
      return
    }
    const reason = validateVaultPath(resolved)
    if (reason) {
      setError(reason)
      return
    }
    // Dispatch is by SOURCE file type, not by target extension:
    //   - md source → POST /api/files. On disk: always `.md`. If the user
    //     re-extensioned the target (e.g. `foo.md` upload typed as
    //     `foo.jpeg`), the doc-id is `foo.jpeg` and the disk file is
    //     `foo.jpeg.md` — the md-wins routing rule serves it back from
    //     URL `/foo.jpeg`.
    //   - non-md source → POST /api/assets. The target keeps whatever
    //     extension the user typed; backend stores the bytes literally.
    const sourceIsMd = file.name.toLowerCase().endsWith('.md')
    setBusy(true)
    try {
      let r: Response
      if (sourceIsMd) {
        const docPath = resolved.toLowerCase().endsWith('.md')
          ? resolved.slice(0, -3)
          : resolved
        const text = await file.text()
        r = await fetch('/api/files', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: docPath, content: text }),
        })
        if (r.ok) {
          onClose()
          void navigate('/' + encodePathToUrl(docPath))
          return
        }
      } else {
        const fd = new FormData()
        fd.append('path', resolved)
        fd.append('file', file, file.name)
        r = await fetch('/api/assets', { method: 'POST', body: fd })
        if (r.ok) {
          onClose()
          void navigate('/' + encodePathToUrl(resolved))
          return
        }
      }
      const detail = await r.text()
      setError(`upload failed: ${r.status} ${detail}`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
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
        <button type="button" className={styles.fileButton} onClick={pickFile}>
          {file ? `${file.name} (${Math.round(file.size / 1024)} KB)` : 'Choose a file…'}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          className={styles.fileInputHidden}
          onChange={onFileChange}
        />
        <input
          ref={inputRef}
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          onKeyDown={onKeyDown}
          type="text"
          className={styles.input}
          placeholder="Upload to vault path…"
          autoComplete="off"
          spellCheck={false}
        />
        {previewPath && (
          <div className={styles.hint}>
            Will save to <code>{previewPath}</code>
          </div>
        )}
        {busy && <div className={styles.hint}>Uploading…</div>}
        {error && <div className={styles.error}>{error}</div>}
      </div>
    </div>
  )
}
