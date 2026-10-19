/**
 * The keyboard model of a tree (WAI-ARIA APG, Tree View pattern), as pure functions: the
 * component keeps the expanded set and the focused id, derives the visible rows, and runs
 * every key through `treeKey`. Nothing here touches the DOM, so it is tested on its own.
 */

export type TreeNode<T> = { id: string; label: string; item: T; children: TreeNode<T>[] }

export type VisibleRow<T> = {
  node: TreeNode<T>
  level: number // 1 for a root (aria-level)
  parentId: string | null
  position: number // 1-based among its siblings (aria-posinset)
  setSize: number // its siblings and itself (aria-setsize)
}

type Flat = { public_id: string; parent: string | null; name: string }

/**
 * Nodes from a flat list whose rows name their parent. Siblings keep the order `compare`
 * gives. A row whose parent is not in the list is left out: it cannot be reached.
 */
export function buildTree<T extends Flat>(rows: readonly T[], compare: (a: T, b: T) => number): TreeNode<T>[] {
  const byParent = new Map<string | null, T[]>()
  for (const row of rows) byParent.set(row.parent, [...(byParent.get(row.parent) ?? []), row])
  const build = (parent: string | null, seen: ReadonlySet<string>): TreeNode<T>[] =>
    (byParent.get(parent) ?? [])
      .filter((row) => !seen.has(row.public_id)) // a cycle in bad data must not loop forever
      .toSorted(compare)
      .map((row) => ({ id: row.public_id, label: row.name, item: row, children: build(row.public_id, new Set([...seen, row.public_id])) }))
  return build(null, new Set())
}

/** The rows a person sees: every root, and the children of every expanded node, in order. */
export function visibleRows<T>(roots: readonly TreeNode<T>[], expanded: ReadonlySet<string>): VisibleRow<T>[] {
  const rows: VisibleRow<T>[] = []
  const walk = (nodes: readonly TreeNode<T>[], level: number, parentId: string | null) => {
    nodes.forEach((node, index) => {
      rows.push({ node, level, parentId, position: index + 1, setSize: nodes.length })
      if (expanded.has(node.id)) walk(node.children, level + 1, node.id)
    })
  }
  walk(roots, 1, null)
  return rows
}

export type TreeAction = {
  focus: string
  expanded: ReadonlySet<string>
  /** Enter: open the focused node (the component navigates to it). */
  activate?: true
}

const isPrintable = (key: string) => key.length === 1 && key !== ' ' && key !== '*'

/**
 * What a key does, from the visible rows, the focused node and the expanded set. Null for a
 * key the tree does not handle (Tab, a modifier chord): the browser keeps it.
 * - Down and Up: the next and previous visible node, no wrap.
 * - Right: opens a closed node, moves into an open one; nothing on a leaf.
 * - Left: closes an open node, else moves to the parent; nothing on a closed root.
 * - Home and End: the first and the last visible node.
 * - Enter: activates the node.
 * - `*`: opens every sibling of the node.
 * - A printable character: the next visible node whose label starts with it, wrapping.
 */
export function treeKey<T>(
  rows: readonly VisibleRow<T>[],
  focused: string,
  key: string,
  expanded: ReadonlySet<string>,
): TreeAction | null {
  const index = rows.findIndex((row) => row.node.id === focused)
  const current = rows[index]
  if (current === undefined) return null
  const node = current.node
  const to = (row: VisibleRow<T> | undefined): TreeAction => ({ focus: row?.node.id ?? focused, expanded })
  const open = (ids: readonly string[]): ReadonlySet<string> => new Set([...expanded, ...ids])
  const isOpen = expanded.has(node.id)
  const hasChildren = node.children.length > 0
  switch (key) {
    case 'ArrowDown':
      return to(rows[index + 1])
    case 'ArrowUp':
      return to(rows[index - 1])
    case 'Home':
      return to(rows[0])
    case 'End':
      return to(rows.at(-1))
    case 'ArrowRight':
      if (!hasChildren) return to(current)
      return isOpen ? to(rows[index + 1]) : { focus: focused, expanded: open([node.id]) }
    case 'ArrowLeft': {
      if (hasChildren && isOpen) return { focus: focused, expanded: new Set([...expanded].filter((id) => id !== node.id)) }
      return to(rows.find((row) => row.node.id === current.parentId))
    }
    case 'Enter':
      return { focus: focused, expanded, activate: true }
    case '*': {
      const siblings = rows.filter((row) => row.parentId === current.parentId && row.node.children.length > 0)
      return { focus: focused, expanded: open(siblings.map((row) => row.node.id)) }
    }
    default: {
      if (!isPrintable(key)) return null
      const wanted = key.toLocaleLowerCase()
      const after = [...rows.slice(index + 1), ...rows.slice(0, index + 1)]
      return to(after.find((row) => row.node.label.toLocaleLowerCase().startsWith(wanted)))
    }
  }
}
