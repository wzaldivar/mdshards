import * as Y from 'yjs'
import { WebsocketProvider } from 'y-websocket'
import { loadConfig } from './config'

export interface DocBundle {
  doc: Y.Doc
  text: Y.Text
  provider: WebsocketProvider
}

/** Re-exported for call sites that still treat the server's grace period
 *  as their concern (Editor's awareness heartbeat). */
export const fetchServerConfig = loadConfig

/** WebSocket server URL — root-anchored to the current origin. WebSockets
 *  don't go through any deployment-prefix layer here; the reverse proxy
 *  is responsible for forwarding `/ws/...` to the backend regardless of
 *  where the SPA shell is mounted. */
function wsServerUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/ws`
}

export function openDoc(docId: string): DocBundle {
  const doc = new Y.Doc()
  const text = doc.getText('content')
  // The provider appends `/${docId}` to the server URL as the room name.
  const provider = new WebsocketProvider(wsServerUrl(), docId, doc)
  return { doc, text, provider }
}

export function closeDoc(bundle: DocBundle): void {
  bundle.provider.disconnect()
  bundle.provider.destroy()
  bundle.doc.destroy()
}
