import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render } from '@testing-library/react'
import { AssetViewer } from '../components/AssetViewer'

/*
 * The AssetViewer picks a rendering strategy by extension: native <img>/
 * <video>/<audio> for media (keyboard shortcuts stay window-level), an
 * iframe for browser-renderable documents (sandboxed only for script-capable
 * types), and an auto-download panel for types the sandbox would otherwise
 * swallow. Every src carries the per-navigation ?v= cache-bust.
 */

const noop = () => {}
const shortcuts = {
  openQuickSwitcher: noop,
  openDeleteSwitcher: noop,
  openRenameSwitcher: noop,
  openUploadSwitcher: noop,
  openEmojiPicker: noop,
  openOptions: noop,
}

function renderAsset(path: string, cacheBust = 'nav-1') {
  return render(<AssetViewer path={path} cacheBust={cacheBust} shortcuts={shortcuts} />)
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('AssetViewer', () => {
  it('renders images as a native <img> with encoded src and cache-bust', () => {
    const { container } = renderAsset('my pics/my pic.png')
    const img = container.querySelector('img')!
    expect(img.getAttribute('src')).toBe('/my%20pics/my%20pic.png?v=nav-1')
    expect(img.getAttribute('alt')).toBe('my pics/my pic.png')
  })

  it('renders video with controls and a captions track', () => {
    const { container } = renderAsset('clip.mp4')
    const video = container.querySelector('video')!
    expect(video.getAttribute('src')).toContain('/clip.mp4?v=')
    expect(video.hasAttribute('controls')).toBe(true)
    expect(video.querySelector('track[kind="captions"]')).not.toBeNull()
  })

  it('renders audio with controls', () => {
    const { container } = renderAsset('song.mp3')
    const audio = container.querySelector('audio')!
    expect(audio.getAttribute('src')).toContain('/song.mp3?v=')
    expect(audio.hasAttribute('controls')).toBe(true)
  })

  it('renders PDFs in an UNsandboxed iframe (sandbox would kill the viewer)', () => {
    const { container } = renderAsset('doc.pdf')
    const iframe = container.querySelector('iframe')!
    expect(iframe.getAttribute('src')).toContain('/doc.pdf?v=')
    expect(iframe.hasAttribute('sandbox')).toBe(false)
  })

  it('sandboxes script-capable types (vault .html can carry external writes)', () => {
    const { container } = renderAsset('page.html')
    const iframe = container.querySelector('iframe')!
    expect(iframe.getAttribute('sandbox')).toBe('allow-same-origin')
  })

  it('auto-downloads archives instead of iframing them, with a manual link', () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const { container } = renderAsset('bundle.zip', 'nav-zip')
    expect(container.querySelector('iframe')).toBeNull()
    expect(click).toHaveBeenCalled()
    const link = container.querySelector('a[download]')!
    expect(link.getAttribute('href')).toContain('/bundle.zip?v=nav-zip')
    expect(link.getAttribute('download')).toBe('bundle.zip')
  })

  it('does not double-fire the auto-download for the same src (StrictMode guard)', () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    renderAsset('twice.zip', 'nav-a')
    cleanup()
    renderAsset('twice.zip', 'nav-a')
    expect(click).toHaveBeenCalledTimes(1)
  })

  it('carries the sub-path prefix on the src when the home-path meta is present', () => {
    const meta = document.createElement('meta')
    meta.setAttribute('name', 'mdshards-home-path')
    meta.setAttribute('content', '/wiki')
    document.head.appendChild(meta)
    try {
      const { container } = renderAsset('pic.png')
      expect(container.querySelector('img')!.getAttribute('src')).toBe('/wiki/pic.png?v=nav-1')
    } finally {
      meta.remove()
    }
  })
})
