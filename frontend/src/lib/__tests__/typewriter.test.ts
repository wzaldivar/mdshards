import { afterEach, describe, expect, it } from 'vitest'
import { EditorView } from '@codemirror/view'
import { EditorState } from '@codemirror/state'
import { centerCurrentLine } from '../typewriter'

/*
 * jsdom has no layout, so we can't assert an actual scroll position. Instead we
 * verify the *trigger* logic — the part that regressed once: typewriter mode
 * must recenter on a local edit (typing is a doc change, NOT a selectionSet),
 * on cursor navigation, and must NOT recenter on programmatic/remote changes
 * (no userEvent) or loop on its own scroll transaction.
 *
 * We detect a recenter by counting update cycles: when centerCurrentLine fires
 * it dispatches a second (scroll) transaction, so a plain counting listener
 * sees two updates for one triggering dispatch instead of one.
 */

let view: EditorView

function makeView() {
  let updates = 0
  view = new EditorView({
    state: EditorState.create({
      doc: Array.from({ length: 100 }, (_, i) => `line ${i}`).join('\n'),
      extensions: [
        centerCurrentLine,
        EditorView.updateListener.of(() => {
          updates += 1
        }),
      ],
    }),
    parent: document.body,
  })
  return {
    /** Update cycles caused by the last action: 2 ⇒ a recenter was dispatched. */
    countFor(action: () => void): number {
      updates = 0
      action()
      return updates
    },
  }
}

afterEach(() => view?.destroy())

describe('centerCurrentLine (typewriter scrolling)', () => {
  it('recenters when the cursor is moved explicitly (arrow/click)', () => {
    const h = makeView()
    expect(h.countFor(() => view.dispatch({ selection: { anchor: 400 } }))).toBe(2)
  })

  it('recenters on a local edit (typing is a doc change, not a selection set)', () => {
    const h = makeView()
    const count = h.countFor(() =>
      view.dispatch({
        changes: { from: view.state.selection.main.head, insert: 'x' },
        userEvent: 'input.type',
      }),
    )
    expect(count).toBe(2)
  })

  it('does NOT recenter on a programmatic/remote change (no userEvent)', () => {
    const h = makeView()
    // Mimics a remote yjs update or ghost-editor external write: doc changes,
    // no selection set, no userEvent tag.
    expect(h.countFor(() => view.dispatch({ changes: { from: 0, insert: 'z' } }))).toBe(1)
  })
})
