import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'

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
 *  Invalid paths (spaces, traversal, ...) come back as 400; surfaced as
 *  `missing` — the user can't have navigated there normally. */
export function useResolve(path: string): ResolveState {
  const navigate = useNavigate()
  const [state, setState] = useState<ResolveState>({ status: 'loading' })

  useEffect(() => {
    let cancelled = false
    setState({ status: 'loading' })
    const stripped = path.replace(/^\/+/, '')
    const url = stripped === '' ? '/api/resolve' : `/api/resolve/${stripped}`
    void (async () => {
      try {
        const r = await fetch(url)
        if (cancelled) return
        if (!r.ok) {
          setState({ status: 'ready', type: 'missing' })
          return
        }
        const body = (await r.json()) as ResolveBody
        if (cancelled) return

        // The backend returns the canonical (no leading slash) form. If it
        // differs from where we are, redirect and let the next render of
        // this hook resolve the canonical URL — at which point canonical
        // will equal stripped and we settle.
        if (body.canonical !== stripped) {
          const target = body.canonical === '' ? '/' : '/' + body.canonical
          void navigate(target, { replace: true })
          return
        }
        setState({ status: 'ready', type: body.type })
      } catch {
        if (cancelled) return
        setState({ status: 'ready', type: 'missing' })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [path, navigate])

  return state
}
