/**
 * A cross-note section link `[[note#Heading]]` navigates to another note whose
 * content loads asynchronously over CRDT, across an Editor remount — so the
 * click that knows the section and the view that can scroll to it live in
 * different Editor instances. The click handler stashes the destination doc-id
 * plus section here; the Editor that next mounts for that doc-id consumes it
 * and scrolls to the heading once the content arrives.
 *
 * One-shot: `takePendingAnchor` returns and clears the section only for a
 * matching doc-id, so an unrelated navigation never inherits a stale jump.
 * (Same module-singleton pattern as `pending-rename.ts`.)
 */

interface PendingAnchor {
  docId: string
  section: string
}

let pending: PendingAnchor | null = null

export function setPendingAnchor(docId: string, section: string): void {
  pending = { docId, section }
}

/** Consume and return the pending section for `docId`, or null if the pending
 *  anchor is absent or was set for a different doc. */
export function takePendingAnchor(docId: string): string | null {
  if (pending === null || pending.docId !== docId) return null
  const { section } = pending
  pending = null
  return section
}
