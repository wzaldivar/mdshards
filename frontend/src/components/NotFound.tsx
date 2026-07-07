import { useNavigate } from 'react-router'
import styles from './NotFound.module.css'

interface Props {
  path: string
}

/** Rendered when `/api/resolve` reports the URL has no matching vault file.
 *  Used to be a silent redirect to `/` — that hid the failure and made it
 *  too easy to mis-type a path without noticing. The card shows the URL the
 *  user tried, a button back to the root, and a reminder that Cmd-K still
 *  works for quick navigation/creation. */
export function NotFound({ path }: Props) {
  const navigate = useNavigate()
  const display = path === '' || path === '/' ? '/' : '/' + path.replace(/^\/+/, '')
  return (
    <div className={styles.host}>
      <div className={styles.card}>
        <h2 className={styles.title}>Not found</h2>
        <p className={styles.body}>
          Nothing in the vault at <code>{display}</code>. The path might be a
          typo, or the file may have been deleted or moved.
        </p>
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.primaryBtn}
            onClick={() => void navigate('/')}
          >
            Go home
          </button>
        </div>
        <p className={styles.hint}>
          Press <kbd>⌘K</kbd> (or <kbd>Ctrl-K</kbd>) to jump to or create a note.
        </p>
      </div>
    </div>
  )
}
