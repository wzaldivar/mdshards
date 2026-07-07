import { describe, expect, it } from 'vitest'
import { diskPathToUrl, flattenTree, type TreeNode } from '../tree'

const sample: TreeNode = {
  name: '',
  path: '',
  type: 'dir',
  children: [
    { name: 'index.md', path: 'index.md', type: 'file' },
    {
      name: 'notes',
      path: 'notes',
      type: 'dir',
      children: [
        { name: 'today.md', path: 'notes/today.md', type: 'file' },
        { name: 'diagram.png', path: 'notes/diagram.png', type: 'file' },
      ],
    },
  ],
}

describe('flattenTree', () => {
  it('returns files and directories by default', () => {
    expect(flattenTree(sample)).toEqual([
      'index.md',
      'notes',
      'notes/today.md',
      'notes/diagram.png',
    ])
  })

  it('with filesOnly, skips dirs', () => {
    expect(flattenTree(sample, { filesOnly: true })).toEqual([
      'index.md',
      'notes/today.md',
      'notes/diagram.png',
    ])
  })
})

describe('diskPathToUrl', () => {
  it('strips a trailing .md', () => {
    expect(diskPathToUrl('notes/today.md')).toBe('notes/today')
  })

  it('leaves non-md paths unchanged', () => {
    expect(diskPathToUrl('notes/diagram.png')).toBe('notes/diagram.png')
  })
})
