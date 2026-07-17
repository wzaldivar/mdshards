import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router'
import { AssetViewer } from '../components/AssetViewer'
import { Editor, type EditorApi } from '../components/Editor'
import { EmojiSwitcher } from '../components/EmojiSwitcher'
import { NotFound } from '../components/NotFound'
import { QuickSwitcher } from '../components/QuickSwitcher'
import { DeleteSwitcher } from '../components/DeleteSwitcher'
import { RenameSwitcher } from '../components/RenameSwitcher'
import { UploadSwitcher } from '../components/UploadSwitcher'
import { OptionsPanel } from '../components/OptionsPanel'
import { routeToDocId } from '../router'
import { encodePathToUrl } from '../lib/paths'
import { bindGlobalShortcuts, type ShortcutHandlers } from '../lib/shortcuts'
import { useResolve } from '../lib/use-resolve'
import styles from './EditorView.module.css'

export function EditorView() {
  const params = useParams()
  const navigate = useNavigate()
  const location = useLocation()

  const docId = useMemo(() => routeToDocId(params['*']), [params])
  const resolved = useResolve(docId)
  // Whether the current URL points at a real file (md or asset). Used to
  // decide which view to mount AND to gate rename/delete — operating on a
  // missing doc would just bubble a 404 from the backend.
  const exists = resolved.status === 'ready' && resolved.type !== 'missing'
  const currentIsMd = resolved.status === 'ready' && resolved.type === 'md'

  const [quickOpen, setQuickOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [renameOpen, setRenameOpen] = useState(false)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [emojiOpen, setEmojiOpen] = useState(false)
  // Seed query for the emoji picker — the shortcode token the cursor was
  // touching when Cmd-E fired (see EditorApi.emojiQueryAtCursor).
  const [emojiSeed, setEmojiSeed] = useState('')
  const [optionsOpen, setOptionsOpen] = useState(false)
  // Imperative bridge into the live CodeMirror buffer (set while an md note
  // is mounted) — the emoji picker inserts through it.
  const editorApiRef = useRef<EditorApi | null>(null)
  const [pendingUploadFile, setPendingUploadFile] = useState<File | null>(null)
  const [movedTo, setMovedTo] = useState<string | null>(null)
  // True while a lost server connection has outlasted the grace window and the
  // editor is locked read-only. Reset automatically when the Editor unmounts
  // (docId change) or reconnects.
  const [connectionLost, setConnectionLost] = useState(false)
  // Hidden file input that Cmd-U triggers via .click(). Owning it here (not
  // inside UploadSwitcher) lets the OS file dialog open BEFORE the modal —
  // the user picks a file, then the modal shows with the path prefilled to
  // `<current dir>/<normalized filename>`, ready to confirm with Enter.
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  function followMove(): void {
    const target = movedTo
    setMovedTo(null)
    if (target !== null) navigate('/' + encodePathToUrl(target))
  }

  function dismissMove(): void {
    setMovedTo(null)
    // Stay on this URL — server already kicked our WS, so the editor is idle.
    // Navigating to '/' avoids confusion since the file at this path is gone.
    navigate('/')
  }

  // Memoize the handler bag — its identity is the dep used by AssetViewer's
  // iframe re-bind effect, and we don't want to thrash the listener on every
  // render. `setX` state setters are stable refs; the closures depend on
  // `docId` (rename root guard) and `exists` (delete/rename presupposes a
  // real file).
  const shortcutHandlers = useMemo<ShortcutHandlers>(() => {
    const closeAll = (): void => {
      setQuickOpen(false)
      setDeleteOpen(false)
      setRenameOpen(false)
      setUploadOpen(false)
      setEmojiOpen(false)
      setOptionsOpen(false)
    }
    return {
      openQuickSwitcher: () => {
        closeAll()
        setQuickOpen(true)
      },
      openDeleteSwitcher: () => {
        if (!exists) return
        closeAll()
        setDeleteOpen(true)
      },
      openRenameSwitcher: () => {
        // Skip on the root index AND when the current path isn't a real file.
        if (docId === '' || !exists) return
        closeAll()
        setRenameOpen(true)
      },
      openUploadSwitcher: () => {
        // Trigger the OS file picker first; the modal opens from the input's
        // onChange below once a file is actually selected. If the user
        // cancels the OS dialog no `change` event fires, so nothing happens
        // — which is the right outcome (no empty modal to dismiss).
        fileInputRef.current?.click()
      },
      openEmojiPicker: () => {
        // Inserting needs a live buffer — only meaningful on an md note.
        if (!currentIsMd) return
        closeAll()
        // Cursor on a `:shortcode` token? Seed the search with it — the pick
        // then REPLACES that token (finish `:smi`, fix `:zmile:`, swap a
        // valid `:smile:` for something else).
        setEmojiSeed(editorApiRef.current?.emojiQueryAtCursor() ?? '')
        setEmojiOpen(true)
      },
      openOptions: () => {
        closeAll()
        setOptionsOpen(true)
      },
    }
  }, [docId, exists, currentIsMd])

  useEffect(() => {
    return bindGlobalShortcuts(shortcutHandlers)
  }, [shortcutHandlers])

  function onUploadFileSelected(e: React.ChangeEvent<HTMLInputElement>): void {
    const file = e.target.files?.[0] ?? null
    // Reset the input so picking the same file twice in a row still fires
    // a change event the second time.
    e.target.value = ''
    if (!file) return
    setQuickOpen(false)
    setDeleteOpen(false)
    setRenameOpen(false)
    setPendingUploadFile(file)
    setUploadOpen(true)
  }

  // Chained ternary in JSX trips S3358; pick the content up front instead.
  let content: React.ReactNode = null
  if (resolved.status !== 'loading') {
    if (resolved.type === 'md') {
      content = (
        <Editor
          key={docId}
          docId={docId}
          onMoved={setMovedTo}
          onReadOnlyChange={setConnectionLost}
          apiRef={editorApiRef}
        />
      )
    } else if (resolved.type === 'asset') {
      content = (
        <AssetViewer
          // Keyed by the navigation (location.key), not just the path: a push
          // to the SAME path — e.g. the upload flow overwriting the asset the
          // user is currently viewing — must remount so the <img>/iframe
          // refetches. The backend serves assets with Cache-Control: no-cache,
          // so the refetch revalidates and picks up the new bytes; without the
          // remount no request happens at all and the stale render sticks.
          key={'asset:' + docId + ':' + location.key}
          path={docId}
          cacheBust={location.key}
          shortcuts={shortcutHandlers}
        />
      )
    } else {
      content = <NotFound path={docId} />
    }
  }

  return (
    <div className={styles.view}>
      {content}
      {connectionLost && (
        <output className={`${styles.banner} ${styles.offline}`}>
          <span className={styles.dino} aria-hidden="true">
            🦖
          </span>
          <span>
            Lost connection to the server — this tab is read-only until it's
            back.
          </span>
        </output>
      )}
      {movedTo !== null && (
        <div className={styles.banner}>
          <span>
            This file was moved to <code>{movedTo}</code>.
          </span>
          <button className={styles.primaryBtn} onClick={followMove}>
            Follow
          </button>
          <button onClick={dismissMove}>Dismiss</button>
        </div>
      )}
      <QuickSwitcher
        open={quickOpen}
        currentDocId={docId}
        onClose={() => setQuickOpen(false)}
      />
      <DeleteSwitcher
        open={deleteOpen}
        currentDocId={docId}
        currentIsMd={currentIsMd}
        onClose={() => setDeleteOpen(false)}
      />
      <RenameSwitcher
        open={renameOpen}
        currentDocId={docId}
        currentIsMd={currentIsMd}
        onClose={() => setRenameOpen(false)}
      />
      <UploadSwitcher
        open={uploadOpen}
        currentDocId={docId}
        initialFile={pendingUploadFile}
        onClose={() => {
          setUploadOpen(false)
          setPendingUploadFile(null)
        }}
      />
      <EmojiSwitcher
        open={emojiOpen}
        initialQuery={emojiSeed}
        onPick={(name, glyph, asGlyph) =>
          asGlyph
            ? editorApiRef.current?.insertGlyph(glyph)
            : editorApiRef.current?.insertShortcode(name)
        }
        onClose={() => {
          setEmojiOpen(false)
          // Cmd-E came from the buffer; Escape should land back in it so
          // typing resumes where it left off.
          editorApiRef.current?.focus()
        }}
      />
      <OptionsPanel open={optionsOpen} onClose={() => setOptionsOpen(false)} />
      <input
        ref={fileInputRef}
        type="file"
        onChange={onUploadFileSelected}
        style={{ display: 'none' }}
      />
    </div>
  )
}
