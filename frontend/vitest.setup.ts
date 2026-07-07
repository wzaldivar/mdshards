import { vi } from 'vitest'

// The Editor opens a `y-websocket` provider on mount; in tests we don't
// want it to actually try to connect (jsdom's URL is now a real
// `http://localhost:5173/` so the provider would otherwise dial it and
// produce noisy unhandled errors from undici's WebSocket internals).
// Stub with a minimal no-op that satisfies y-websocket's expectations.
class StubWebSocket {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3
  readonly CONNECTING = 0
  readonly OPEN = 1
  readonly CLOSING = 2
  readonly CLOSED = 3
  readyState = 0
  url: string
  binaryType: 'arraybuffer' | 'blob' = 'arraybuffer'
  onopen: ((this: WebSocket, ev: Event) => unknown) | null = null
  onerror: ((this: WebSocket, ev: Event) => unknown) | null = null
  onclose: ((this: WebSocket, ev: CloseEvent) => unknown) | null = null
  onmessage: ((this: WebSocket, ev: MessageEvent) => unknown) | null = null
  constructor(url: string) {
    this.url = url
  }
  addEventListener(): void {}
  removeEventListener(): void {}
  send(): void {}
  close(): void {}
  dispatchEvent(): boolean {
    return false
  }
}

vi.stubGlobal('WebSocket', StubWebSocket)
