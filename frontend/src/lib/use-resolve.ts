import { backendUrl } from './backend'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { encodePathToUrl } from './paths'

export type ResourceType = 'md' | 'asset' | 'missing'

export type ResolveState =
  | { status: 'loading' }
  | { status: 'ready'; type: ResourceType }

interface ResolveBody {
  type: ResourceType
  /** Canonical URL form for this resource, without a leading slash. The
   *  backend rewrites `.md` URLs whose md-doc-id form isn't on disk down to
   *  their extensionless form here — the hook navigates(replace) to match. */
  canonical: string
}

/** Ask the backend what kind of resource lives at a URL path. Called on
 *  every navigation by EditorView. When the backend reports a canonical URL
 *  that differs from the current pathname, the hook performs a replace
 *  navigation so the user lands on the canonical form before any state
 *  (Editor doc-id, AssetViewer src, switcher prefill) is computed.
 *
 *  Invalid paths (traversal, backslash, ...) come back as 400; surfaced as
 *  `missing` — the user can't have navigated there normally.
 *
 *  `docId` is the RAW (decoded) vault path — react-router decodes the splat
 *  param, so spaces arrive as literal spaces here. We percent-encode when
 *  building the fetch URL and when navigating to the canonical form, but the
 *  `canonical` comparison is done raw-vs-raw (the backend returns the decoded
 *  form) so a spaced note doesn't ping-pong between encoded/decoded URLs. */
export function useResolve(docId: string): ResolveState {
  const navigate = useNavigate()
  // The ready state is tagged with the docId it describes. On the first
  // render after a navigation — before this hook's effect has run — `state`
  // still describes the PREVIOUS docId; returning it as-is would let
  // EditorView mount an Editor (and open a WebSocket) for the new path a
  // beat before the reset to `loading` unmounts it again. That churn opens
  // sockets that are immediately closed mid-handshake, which Safari
  // mishandles badly enough to wedge the doc's next connection.
  const [state, setState] = useState<{ for: string; res: ResolveState }>({
    for: docId,
    res: { status: 'loading' },
  })

  useEffect(() => {
    let cancelled = false
    setState({ for: docId, res: { status: 'loading' } })
    const stripped = docId.replace(/^\/+/, '')
    const url = backendUrl(
      stripped === '' ? '/api/resolve' : `/api/resolve/${encodePathToUrl(stripped)}`,
    )
    void (async () => {
      try {
        const r = await fetch(url)
        if (cancelled) return
        if (!r.ok) {
          setState({ for: docId, res: { status: 'ready', type: 'missing' } })
          return
        }
        const body = (await r.json()) as ResolveBody
        if (cancelled) return

        // The backend returns the canonical (no leading slash) form. If it
        // differs from where we are, redirect and let the next render of
        // this hook resolve the canonical URL — at which point canonical
        // will equal stripped and we settle.
        if (body.canonical !== stripped) {
          const target = body.canonical === '' ? '/' : '/' + encodePathToUrl(body.canonical)
          void navigate(target, { replace: true })
          return
        }
        setState({ for: docId, res: { status: 'ready', type: body.type } })
      } catch {
        if (cancelled) return
        setState({ for: docId, res: { status: 'ready', type: 'missing' } })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [docId, navigate])

  // A state describing a different docId means we're mid-navigation and the
  // effect hasn't caught up yet — that's a loading gap, not the old answer.
  return state.for === docId ? state.res : { status: 'loading' }
}
