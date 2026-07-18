import * as Y from 'yjs'
import { WebsocketProvider } from 'y-websocket'
import { apiUrl, backendWsUrl } from './backend'
import { encodePathToUrl } from './paths'

export interface DocBundle {
  doc: Y.Doc
  text: Y.Text
  provider: WebsocketProvider
}

/** Re-exported for call sites that still treat the server's grace period
 *  as their concern (Editor's awareness heartbeat). */
export { loadConfig as fetchServerConfig } from './config'

/** Ask the server where a doc went after a move/conflict. Used when the
 *  WebSocket dropped without a usable close code (Safari/WebKit reports our app
 *  close codes as a bare 1006 and drops the reason), so the tab can still offer
 *  an explicit link to the new location. Returns the destination doc-id, or
 *  null when there's no recent forward (the common case: an ordinary drop). */
export async function fetchMovedTarget(docId: string): Promise<string | null> {
  try {
    const url = apiUrl(docId === '' ? '/api/moved' : `/api/moved/${encodePathToUrl(docId)}`)
    const res = await fetch(url)
    if (!res.ok) return null
    const body = (await res.json()) as { target: string | null }
    return body.target ?? null
  } catch {
    return null
  }
}


export function openDoc(docId: string): DocBundle {
  const doc = new Y.Doc()
  const text = doc.getText('content')
  // The provider appends `/${room}` to the server URL as the room name and
  // does NOT encode it, so we percent-encode here — otherwise a doc-id with a
  // space (or `#`/`?`) would produce a malformed WS URL. The backend decodes
  // the `{doc_id:path}` param, keying the doc by the raw path again.
  //
  // `connect: false`: the caller decides when to open the socket (the Editor
  // defers it by one task). A bundle torn down before that tick never opens
  // a WebSocket at all — closing a socket mid-handshake is what Safari
  // mishandles: the aborted CONNECTING socket can wedge the next connection
  // to the same URL, leaving the doc permanently unsynced (blank note).
  // `resyncInterval`: y-websocket force-reconnects when it hears nothing from
  // the server for 30s (`messageReconnectTimeout`), and an idle note produces
  // exactly that silence — so every idle tab was micro-cutting its socket
  // every ~30s. Chrome reconnects invisibly; Safari throttles unfocused
  // windows enough that the reconnect can lose the race against the
  // read-only countdown, flashing the offline dino at random. The periodic
  // SyncStep1 request draws a server reply that keeps the connection
  // recognized as alive.
  const provider = new WebsocketProvider(backendWsUrl(), encodePathToUrl(docId), doc, {
    connect: false,
    resyncInterval: 10_000,
  })
  return { doc, text, provider }
}

export function closeDoc(bundle: DocBundle): void {
  bundle.provider.disconnect()
  bundle.provider.destroy()
  bundle.doc.destroy()
}
