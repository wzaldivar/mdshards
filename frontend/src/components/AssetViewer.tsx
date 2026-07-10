import { backendUrl } from '../lib/backend'
import { useEffect, useRef } from 'react'
import { frameModeFor, kindFor } from '../lib/asset-kind'
import { bindShortcuts, type ShortcutHandlers } from '../lib/shortcuts'
import { encodePathToUrl } from '../lib/paths'
import styles from './AssetViewer.module.css'

interface Props {
  path: string
  /** Opaque per-navigation token (EditorView passes react-router's
   *  `location.key`). Appended to the asset URL as a `?v=` query param so
   *  each visit fetches under a fresh URL: browsers' in-memory image cache
   *  reuses already-decoded images by URL for the lifetime of the SPA's
   *  document WITHOUT revalidating, so after an upload overwrites the asset,
   *  a same-URL <img> would keep showing the old pixels no matter what
   *  Cache-Control says. Only the rendered src carries the param — the vault
   *  file and markdown references stay untouched (portability rule). */
  cacheBust: string
  /** The same handler bag used at the window level. Re-attached inside the
   *  iframe's contentDocument so Cmd-K et al. keep firing when focus moves
   *  into the embedded asset viewer (e.g. clicking on an iframe). */
  shortcuts: ShortcutHandlers
}

/** Renders a vault asset inside the editor chrome. Images / video / audio are
 *  rendered with native HTML elements so they sit inside the Catppuccin
 *  surface (centered, themed background, soft shadow) and don't trap keyboard
 *  focus — window-level shortcuts just work. Everything else falls back to an
 *  iframe so the browser's native viewer (PDFs, text, etc.) handles it; the
 *  iframe path re-binds shortcuts inside its contentDocument when possible. */
export function AssetViewer({ path, cacheBust, shortcuts }: Props) {
  // `path` is the raw vault path (spaces intact); encode for the fetchable src.
  const src = backendUrl('/' + encodePathToUrl(path) + '?v=' + encodeURIComponent(cacheBust))
  const kind = kindFor(path)

  if (kind === 'image') {
    return (
      <div className={styles.host}>
        <img className={styles.image} src={src} alt={path} />
      </div>
    )
  }
  if (kind === 'video') {
    return (
      <div className={styles.host}>
        <video className={styles.video} src={src} controls />
      </div>
    )
  }
  if (kind === 'audio') {
    return (
      <div className={styles.host}>
        <audio className={styles.audio} src={src} controls />
      </div>
    )
  }

  // Non-media assets: browser-default handling by default. Only
  // script-capable types get the sandbox (it also blocks the PDF viewer and
  // download fallbacks, so it must not be blanket); known archives skip the
  // iframe for the download panel. Everything else — pdf, text, code,
  // unknown extensions — goes into a plain iframe where the browser renders
  // what it can and natively downloads what it can't. The backend mirrors
  // the same split for its `CSP: sandbox` response header (pages.py).
  const mode = frameModeFor(path)
  if (mode === 'download') {
    return <DownloadAsset src={src} path={path} />
  }
  return (
    <IframeAsset src={src} title={path} shortcuts={shortcuts} sandboxed={mode === 'sandboxed'} />
  )
}

/** Guard against back-to-back duplicate auto-downloads of the same URL —
 *  React StrictMode double-mounts effects in dev, which would otherwise
 *  save the file twice on every visit. */
let lastAutoDownload = { src: '', at: 0 }

/** Non-viewable asset (zip, tarball, arbitrary binary): rendering it is
 *  impossible and the sandboxed iframe would silently BLOCK the browser's
 *  download fallback, leaving a blank page. Hand control back to the
 *  browser instead — kick off its native download on arrival and show a
 *  panel with a manual link in case the auto-start was blocked. */
function DownloadAsset({ src, path }: { src: string; path: string }) {
  const basename = path.slice(path.lastIndexOf('/') + 1)

  useEffect(() => {
    const now = Date.now()
    if (lastAutoDownload.src === src && now - lastAutoDownload.at < 1000) return
    lastAutoDownload = { src, at: now }
    const a = document.createElement('a')
    a.href = src
    a.download = basename
    a.click()
  }, [src, basename])

  return (
    <div className={styles.host}>
      <div className={styles.downloadPanel}>
        <span className={styles.downloadName}>{basename}</span>
        <span className={styles.downloadHint}>
          This file type can't be previewed — downloading it instead.
        </span>
        <a className={styles.downloadLink} href={src} download={basename}>
          Download again
        </a>
      </div>
    </div>
  )
}

function IframeAsset({
  src,
  title,
  shortcuts,
  sandboxed,
}: {
  src: string
  title: string
  shortcuts: ShortcutHandlers
  sandboxed: boolean
}) {
  const iframeRef = useRef<HTMLIFrameElement | null>(null)

  useEffect(() => {
    const iframe = iframeRef.current
    if (!iframe) return
    let unbind: (() => void) | null = null

    // The iframe's contentDocument is the browsing context that owns keydown
    // events while focus is inside it. Same-origin assets (text, anything the
    // backend serves directly) expose this document so we can attach the same
    // listener. Cross-origin viewers (Chrome's built-in PDF viewer runs at
    // chrome-extension://… and is opaque to us) silently fall back to the
    // window-level binding — the user has to click outside the iframe to
    // regain focus, which is the best we can do without rewriting the viewer.
    const attach = (): void => {
      unbind?.()
      unbind = null
      try {
        const docu = iframe.contentDocument
        if (!docu) return
        unbind = bindShortcuts(docu, shortcuts)
      } catch {
        // Cross-origin — accessing contentDocument throws a SecurityError.
      }
    }

    iframe.addEventListener('load', attach)
    // Try once now in case the iframe was already loaded before this effect ran
    // (StrictMode double-invoke, fast cache, etc.).
    attach()
    return () => {
      iframe.removeEventListener('load', attach)
      unbind?.()
    }
  }, [shortcuts, src])

  return (
    <div className={styles.host}>
      {/*
        `sandbox="allow-same-origin"` disables scripts, forms, popups, and top
        navigation inside the iframe — critical because the vault may receive
        external writes (Syncthing/Obsidian), so an `.html` file could
        otherwise execute attacker JS in the SPA's own origin. We KEEP
        `allow-same-origin` (without `allow-scripts`) so the parent can still
        attach the shortcut listener on `contentDocument` for text/PDF assets;
        adding `allow-scripts` alongside `allow-same-origin` would defeat the
        sandbox per the MDN warning.
      */}
      <iframe
        ref={iframeRef}
        className={styles.frame}
        src={src}
        title={title}
        {...(sandboxed ? { sandbox: 'allow-same-origin' } : {})}
      />
    </div>
  )
}
