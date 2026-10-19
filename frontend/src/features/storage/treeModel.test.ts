import { describe, expect, it } from 'vitest'
import { buildTree, treeKey, type TreeNode, visibleRows } from './treeModel'

type Row = { public_id: string; parent: string | null; name: string; slot: number | null }

// Freezer A > Rack 1 > Box 1, Box 2; Freezer A > Rack 2 > Box 3; Tank B > Rack 9.
const ROWS: Row[] = [
  { public_id: 'tank', parent: null, name: 'Tank B', slot: null },
  { public_id: 'box2', parent: 'rack1', name: 'Box 2', slot: 2 },
  { public_id: 'freezer', parent: null, name: 'Freezer A', slot: null },
  { public_id: 'rack1', parent: 'freezer', name: 'Rack 1', slot: 1 },
  { public_id: 'box1', parent: 'rack1', name: 'Box 1', slot: 1 },
  { public_id: 'rack2', parent: 'freezer', name: 'Rack 2', slot: 2 },
  { public_id: 'box3', parent: 'rack2', name: 'Box 3', slot: null },
  { public_id: 'rack9', parent: 'tank', name: 'Rack 9', slot: null },
]
const bySlotThenName = (a: Row, b: Row) => (a.slot ?? Infinity) - (b.slot ?? Infinity) || a.name.localeCompare(b.name)
const roots = buildTree(ROWS, bySlotThenName)
const ids = (rows: { node: TreeNode<Row> }[]) => rows.map((row) => row.node.id)
const visible = (expanded: string[]) => visibleRows(roots, new Set(expanded))
const press = (key: string, focused: string, expanded: string[]) => treeKey(visible(expanded), focused, key, new Set(expanded))

describe('buildTree', () => {
  it('nests rows under their parents, siblings in the given order', () => {
    expect(roots.map((n) => n.id)).toEqual(['freezer', 'tank'])
    const freezer = roots[0]
    expect(freezer?.children.map((n) => n.id)).toEqual(['rack1', 'rack2'])
    expect(freezer?.children[0]?.children.map((n) => n.id)).toEqual(['box1', 'box2'])
  })

  it('leaves out a row whose parent it does not have, and survives a cycle in bad data', () => {
    const tree = buildTree(
      [
        { public_id: 'a', parent: 'b', name: 'A', slot: null },
        { public_id: 'b', parent: 'a', name: 'B', slot: null },
        { public_id: 'c', parent: 'missing', name: 'C', slot: null },
        { public_id: 'r', parent: null, name: 'R', slot: null },
      ],
      bySlotThenName,
    )
    expect(tree.map((n) => n.id)).toEqual(['r'])
  })
})

describe('visibleRows', () => {
  it('shows the roots, and the children of open nodes only, with level, position and set size', () => {
    expect(ids(visible([]))).toEqual(['freezer', 'tank'])
    const rows = visible(['freezer', 'rack1'])
    expect(ids(rows)).toEqual(['freezer', 'rack1', 'box1', 'box2', 'rack2', 'tank'])
    expect(rows.map((r) => [r.level, r.position, r.setSize, r.parentId])).toEqual([
      [1, 1, 2, null],
      [2, 1, 2, 'freezer'],
      [3, 1, 2, 'rack1'],
      [3, 2, 2, 'rack1'],
      [2, 2, 2, 'freezer'],
      [1, 2, 2, null],
    ])
  })

  it('hides the children of an open node under a closed one', () => {
    expect(ids(visible(['rack1']))).toEqual(['freezer', 'tank'])
  })
})

describe('treeKey (APG tree view)', () => {
  const open = ['freezer', 'rack1']

  it('moves down and up through the visible nodes without wrapping', () => {
    expect(press('ArrowDown', 'freezer', open)?.focus).toBe('rack1')
    expect(press('ArrowDown', 'box2', open)?.focus).toBe('rack2')
    expect(press('ArrowDown', 'tank', open)?.focus).toBe('tank')
    expect(press('ArrowUp', 'rack2', open)?.focus).toBe('box2')
    expect(press('ArrowUp', 'freezer', open)?.focus).toBe('freezer')
  })

  it('opens a closed node on Right and keeps the focus, then moves into it', () => {
    const opened = press('ArrowRight', 'rack2', open)
    expect(opened?.focus).toBe('rack2')
    expect([...(opened?.expanded ?? [])].toSorted()).toEqual(['freezer', 'rack1', 'rack2'])
    expect(press('ArrowRight', 'rack1', open)).toEqual({ focus: 'box1', expanded: new Set(open) })
  })

  it('does nothing on Right on a leaf', () => {
    expect(press('ArrowRight', 'box1', open)).toEqual({ focus: 'box1', expanded: new Set(open) })
  })

  it('closes an open node on Left, else moves to the parent, and stays on a closed root', () => {
    const closed = press('ArrowLeft', 'rack1', open)
    expect(closed?.focus).toBe('rack1')
    expect([...(closed?.expanded ?? [])]).toEqual(['freezer'])
    expect(press('ArrowLeft', 'box2', open)?.focus).toBe('rack1')
    expect(press('ArrowLeft', 'rack2', open)?.focus).toBe('freezer')
    expect(press('ArrowLeft', 'tank', open)).toEqual({ focus: 'tank', expanded: new Set(open) })
  })

  it('goes to the first and the last visible node on Home and End', () => {
    expect(press('Home', 'box2', open)?.focus).toBe('freezer')
    expect(press('End', 'box1', open)?.focus).toBe('tank')
  })

  it('activates the focused node on Enter', () => {
    expect(press('Enter', 'box1', open)).toEqual({ focus: 'box1', expanded: new Set(open), activate: true })
  })

  it('opens every sibling that has children on *', () => {
    const all = press('*', 'freezer', [])
    expect([...(all?.expanded ?? [])].toSorted()).toEqual(['freezer', 'tank'])
    expect(all?.focus).toBe('freezer')
  })

  it('jumps to the next node whose name starts with a typed character, wrapping', () => {
    expect(press('b', 'rack1', open)?.focus).toBe('box1')
    expect(press('B', 'box1', open)?.focus).toBe('box2')
    expect(press('f', 'tank', open)?.focus).toBe('freezer')
    expect(press('z', 'rack1', open)?.focus).toBe('rack1')
  })

  it('leaves every other key to the browser', () => {
    for (const key of ['Tab', 'Shift', ' ', 'PageDown', 'Escape']) expect(press(key, 'rack1', open)).toBeNull()
  })

  it('does nothing for a focused id it does not show', () => {
    expect(press('ArrowDown', 'box1', [])).toBeNull()
  })
})
