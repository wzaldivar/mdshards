/** Attribute bag that tells browsers AND password-manager extensions to keep
 *  their autofill/autocomplete UI away from an input. The switcher/picker
 *  search fields are transient command-palette inputs — a Bitwarden overlay
 *  on them is pure noise.
 *
 *  `autocomplete="off"` alone is routinely ignored by both browsers and
 *  extensions, so this adds each vendor's documented opt-out:
 *    - Bitwarden  → `data-bwignore`
 *    - 1Password  → `data-1p-ignore`
 *    - LastPass   → `data-lpignore="true"`
 *    - Dashlane   → `data-form-type="other"`
 *  plus the mobile-Safari trio (autocorrect/autocapitalize/spellcheck).
 *  Best effort by nature — extensions can and do change their heuristics. */
export const NO_AUTOFILL = {
  autoComplete: 'off',
  autoCorrect: 'off',
  autoCapitalize: 'off',
  spellCheck: false,
  'data-bwignore': 'true',
  'data-1p-ignore': 'true',
  'data-lpignore': 'true',
  'data-form-type': 'other',
} as const
