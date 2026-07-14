import type { ReactNode, Ref } from 'react'
import { NO_AUTOFILL } from '../lib/no-autofill'
import styles from './Switcher.module.css'

interface Props {
  inputRef: Ref<HTMLInputElement>
  value: string
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void
  onKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => void
  placeholder: string
  onClose: () => void
  /** Extra modal content rendered BEFORE the text input — the upload
   *  switcher's file-picker button. Omitted by the others. */
  beforeInput?: ReactNode
  /** The result list, hints, and error surface — rendered after the input. */
  children: ReactNode
}

/** The shared modal chrome for every keyboard-first switcher: the dimmed
 *  backdrop, a click-outside-to-close scrim, the framed modal, and the text
 *  input. Each switcher supplies its own state/handlers and its own list body
 *  as `children`; the `if (!open) return null` guard stays with the caller. */
export function SwitcherShell({
  inputRef,
  value,
  onChange,
  onKeyDown,
  placeholder,
  onClose,
  beforeInput,
  children,
}: Readonly<Props>) {
  return (
    <div className={styles.backdrop}>
      {/* Click-outside-to-close catcher. A native <button> (not a div with
          onClick) keeps it accessible without per-element key handlers;
          tabIndex=-1 keeps keyboard focus in the input. */}
      <button
        type="button"
        className={styles.scrim}
        aria-label="Close"
        tabIndex={-1}
        onClick={onClose}
      />
      <div className={styles.modal}>
        {beforeInput}
        <input
          ref={inputRef}
          value={value}
          onChange={onChange}
          onKeyDown={onKeyDown}
          type="text"
          className={styles.input}
          placeholder={placeholder}
          {...NO_AUTOFILL}
        />
        {children}
      </div>
    </div>
  )
}
