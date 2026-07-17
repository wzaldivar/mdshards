import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { OptionsPanel } from '../components/OptionsPanel'
import { EmojiSwitcher } from '../components/EmojiSwitcher'
import { getEditorPrefs, setEditorPref } from '../lib/editor-prefs'

/*
 * The two remaining modal surfaces: the editor options panel (local prefs +
 * ⌥-accelerators + the relative-numbers dependency rule) and the Cmd-E
 * emoji picker (seeded query, alias search, Enter/click insertion of the
 * shortcode NAME — the file keeps `:name:`, never the glyph).
 */

function resetPrefs(): void {
  for (const key of ['vim', 'lineNumbers', 'relativeLineNumbers', 'centerLine'] as const) {
    setEditorPref(key, false)
  }
}

afterEach(() => {
  cleanup()
  resetPrefs()
  localStorage.clear()
})

describe('OptionsPanel', () => {
  it('renders the four pref rows and toggles via checkbox click', async () => {
    render(<OptionsPanel open onClose={() => {}} />)
    await screen.findByText(/editor options/i)
    const vim = screen.getByRole('checkbox', { name: /vim mode/i })
    expect((vim as HTMLInputElement).checked).toBe(false)
    fireEvent.click(vim)
    expect(getEditorPrefs().vim).toBe(true)
  })

  it('keeps relative line numbers gated behind line numbers', async () => {
    render(<OptionsPanel open onClose={() => {}} />)
    const rel = (await screen.findByRole('checkbox', {
      name: /relative line numbers/i,
    })) as HTMLInputElement
    expect(rel.disabled).toBe(true)
    // enabling the prerequisite un-gates the row
    fireEvent.click(screen.getByRole('checkbox', { name: /show line numbers/i }))
    await waitFor(() => expect(rel.disabled).toBe(false))
    fireEvent.click(rel)
    expect(getEditorPrefs().relativeLineNumbers).toBe(true)
  })

  it('⌥-accelerators toggle rows; gated rows ignore theirs', async () => {
    render(<OptionsPanel open onClose={() => {}} />)
    await screen.findByText(/editor options/i)
    fireEvent.keyDown(window, { code: 'KeyV', altKey: true })
    expect(getEditorPrefs().vim).toBe(true)
    // ⌥R is inert while line numbers are off
    fireEvent.keyDown(window, { code: 'KeyR', altKey: true })
    expect(getEditorPrefs().relativeLineNumbers).toBe(false)
    fireEvent.keyDown(window, { code: 'KeyN', altKey: true })
    fireEvent.keyDown(window, { code: 'KeyR', altKey: true })
    expect(getEditorPrefs().relativeLineNumbers).toBe(true)
  })

  it('Escape closes; prefs changed in another tab reflect live', async () => {
    const onClose = vi.fn()
    render(<OptionsPanel open onClose={onClose} />)
    const vim = (await screen.findByRole('checkbox', { name: /vim mode/i })) as HTMLInputElement
    // a write from anywhere (other tab via storage event → prefs pub/sub)
    setEditorPref('vim', true)
    await waitFor(() => expect(vim.checked).toBe(true))
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })

  it('renders nothing when closed', () => {
    render(<OptionsPanel open={false} onClose={() => {}} />)
    expect(screen.queryByText(/editor options/i)).toBeNull()
  })
})

describe('EmojiSwitcher', () => {
  it('searches the gemoji dataset and inserts the picked NAME on Enter', async () => {
    const onPick = vi.fn()
    render(<EmojiSwitcher open initialQuery="" onPick={onPick} onClose={() => {}} />)
    const input = await screen.findByPlaceholderText(/insert emoji/i)
    fireEvent.change(input, { target: { value: 't-rex' } })
    await screen.findByRole('button', { name: /🦖 :t-rex:/ })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onPick).toHaveBeenCalledWith('t-rex', '🦖', false)
  })

  it('inserts the literal glyph (not the name) on Shift-Enter', async () => {
    const onPick = vi.fn()
    render(<EmojiSwitcher open initialQuery="" onPick={onPick} onClose={() => {}} />)
    const input = await screen.findByPlaceholderText(/insert emoji/i)
    fireEvent.change(input, { target: { value: 't-rex' } })
    await screen.findByRole('button', { name: /🦖 :t-rex:/ })
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true })
    expect(onPick).toHaveBeenCalledWith('t-rex', '🦖', true)
  })

  it('matches by alias/description, not just the primary name', async () => {
    const onPick = vi.fn()
    render(<EmojiSwitcher open initialQuery="" onPick={onPick} onClose={() => {}} />)
    const input = await screen.findByPlaceholderText(/insert emoji/i)
    fireEvent.change(input, { target: { value: 'thumbs up' } })
    await screen.findByRole('button', { name: /👍 :\+1:/ })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onPick).toHaveBeenCalledWith('+1', '👍', false)
  })

  it('seeds the query from the touched token and arrows move the pick', async () => {
    const onPick = vi.fn()
    render(<EmojiSwitcher open initialQuery="smile" onPick={onPick} onClose={() => {}} />)
    const input = (await screen.findByPlaceholderText(/insert emoji/i)) as HTMLInputElement
    expect(input.value).toBe('smile')
    await screen.findByRole('button', { name: /:smile:/ }) // dataset loaded
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onPick).toHaveBeenCalled()
    expect(onPick.mock.calls[0][0]).toContain('smile')
  })

  it('closes on Escape without picking', async () => {
    const onPick = vi.fn()
    const onClose = vi.fn()
    render(<EmojiSwitcher open initialQuery="" onPick={onPick} onClose={onClose} />)
    const input = await screen.findByPlaceholderText(/insert emoji/i)
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
    expect(onPick).not.toHaveBeenCalled()
  })
})
