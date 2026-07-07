export interface TreeNode {
  name: string
  path: string
  type: 'file' | 'dir'
  children?: TreeNode[]
}

export async function fetchTree(): Promise<TreeNode> {
  // Origin-rooted, like every other API call — the bundle is base-url-agnostic
  // and the reverse proxy routes `/api/*` to the backend (see CLAUDE.md). A
  // relative `api/tree` would resolve against the current document path, so
  // from a nested doc like `/foo/bar` it hit `/foo/api/tree` → SPA shell →
  // "Unexpected token '<'" JSON parse error.
  const r = await fetch('/api/tree')
  if (!r.ok) throw new Error(`tree fetch failed: ${r.status}`)
  return (await r.json()) as TreeNode
}

/** Flatten the tree into a list of paths (files only, by default). */
export function flattenTree(root: TreeNode, opts: { filesOnly?: boolean } = {}): string[] {
  const out: string[] = []
  const walk = (node: TreeNode): void => {
    if (node.type === 'file') {
      out.push(node.path)
    } else if (!opts.filesOnly && node.path !== '') {
      out.push(node.path)
    }
    node.children?.forEach(walk)
  }
  walk(root)
  return out
}

/** Convert an on-disk vault file path (e.g. `notes/today.md`) to the URL path
 * the editor uses (`notes/today`). Non-md paths are returned unchanged. */
export function diskPathToUrl(p: string): string {
  return p.endsWith('.md') ? p.slice(0, -3) : p
}
