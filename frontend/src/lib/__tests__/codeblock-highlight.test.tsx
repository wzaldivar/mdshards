import { afterEach, describe, expect, it } from 'vitest'
import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { markdown } from '@codemirror/lang-markdown'
import { languages as codeLanguages } from '@codemirror/language-data'

/*
 * Smoke test for the per-language code-block hookup. We can't easily test
 * the *rendered tokens* — `@codemirror/language-data` lazy-loads the
 * language packs via dynamic `import()`, which doesn't complete
 * synchronously in jsdom. Instead we verify:
 *   (1) `codeLanguages` resolves a real LanguageDescription for `python`
 *       and `typescript` (otherwise we know nothing else will work);
 *   (2) the editor mounts without throwing when those code blocks are
 *       present, which catches regressions in the parser config.
 */

let view: EditorView | null = null

afterEach(() => {
  view?.destroy()
  view = null
  document.body.innerHTML = ''
})

describe('fenced code block syntax highlighting hookup', () => {
  it('language-data ships descriptors for the common languages', () => {
    const names = codeLanguages.map((l) => l.name.toLowerCase())
    // Spot-check a few — the full list is huge but this catches a totally
    // broken import (empty / mis-spelled key).
    for (const lang of ['javascript', 'typescript', 'python', 'json', 'rust']) {
      expect(names).toContain(lang)
    }
  })

  it('the markdown extension accepts codeLanguages without errors', () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const doc =
      '# A note\n\nSome prose, then code:\n\n```python\ndef foo(n):\n    return n * 2\n```\n\nDone.\n'
    expect(() => {
      view = new EditorView({
        state: EditorState.create({
          doc,
          extensions: [markdown({ codeLanguages })],
        }),
        parent: host,
      })
    }).not.toThrow()
    // The fenced block should land in the DOM as `.cm-line` content with
    // the source text intact (parsing succeeded even if the language pack
    // is still loading asynchronously).
    const lines = Array.from(document.querySelectorAll('.cm-line'))
    const hasFenceLine = lines.some((l) => l.textContent?.trim() === '```python')
    expect(hasFenceLine).toBe(true)
  })
})
