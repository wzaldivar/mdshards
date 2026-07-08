import { EditorView } from '@codemirror/view'
import { Transaction } from '@codemirror/state'

/** "Typewriter scrolling": keep the line holding the cursor vertically
 *  centered. `scrollIntoView(head, {y: 'center'})` clamps at the document
 *  edges, so near the top or bottom of the file the line sits where it
 *  naturally falls instead of forcing blank space above/below — i.e. centered
 *  *unless* at the beginning or end of the file.
 *
 *  Fires on any *local* cursor move or edit: `selectionSet` covers arrow/click
 *  navigation, and a user text edit (typing, delete, paste) is tagged with a
 *  `userEvent`. Purely programmatic doc changes — remote yjs updates and the
 *  ghost editor's external-write splices — carry no user event and don't set
 *  the selection, so they stream in without yanking the viewport around. The
 *  scroll-only transaction we emit has neither, so it can't re-trigger this
 *  listener (no loop). Dispatching from an update listener is safe: CodeMirror
 *  resets its update state to idle before invoking listeners. */
export const centerCurrentLine = EditorView.updateListener.of((update) => {
  const localMove =
    update.selectionSet ||
    update.transactions.some((tr) => tr.annotation(Transaction.userEvent) !== undefined)
  if (!localMove) return
  const head = update.state.selection.main.head
  update.view.dispatch({ effects: EditorView.scrollIntoView(head, { y: 'center' }) })
})
