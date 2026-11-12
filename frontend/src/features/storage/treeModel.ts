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

/** The keys that only move the focus: the row they land on, from the rows and the focused index. */
const JUMPS: Readonly<Record<string, <T>(rows: readonly VisibleRow<T>[], index: number) => VisibleRow<T> | undefined>> = {
  ArrowDown: (rows, index) => rows[index + 1],
  ArrowUp: (rows, index) => rows[index - 1],
  Home: (rows) => rows[0],
  End: (rows) => rows.at(-1),
}

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
  const to = (row: VisibleRow<T> | undefined): TreeAction => ({ focus: row?.node.id ?? focused, expanded })
  const jump = JUMPS[key]
  if (jump) return to(jump(rows, index))
  switch (key) {
    case 'ArrowRight':
      return openOrEnter(current, rows[index + 1], expanded)
    case 'ArrowLeft':
      return closeOrLeave(rows, current, expanded)
    case 'Enter':
      return { focus: focused, expanded, activate: true }
    case '*':
      return openSiblings(rows, current, expanded)
    default:
      return isPrintable(key) ? to(nextStartingWith(rows, index, key)) : null
  }
}

/** Right: opens a closed node, moves into an open one; nothing on a leaf. */
function openOrEnter<T>(current: VisibleRow<T>, next: VisibleRow<T> | undefined, expanded: ReadonlySet<string>): TreeAction {
  const id = current.node.id
  if (current.node.children.length === 0) return { focus: id, expanded }
  if (expanded.has(id)) return { focus: next?.node.id ?? id, expanded }
  return { focus: id, expanded: new Set([...expanded, id]) }
}

/** Left: closes an open node, else moves to the parent; nothing on a closed root. */
function closeOrLeave<T>(rows: readonly VisibleRow<T>[], current: VisibleRow<T>, expanded: ReadonlySet<string>): TreeAction {
  const id = current.node.id
  if (current.node.children.length > 0 && expanded.has(id)) return { focus: id, expanded: new Set([...expanded].filter((open) => open !== id)) }
  const parent = rows.find((row) => row.node.id === current.parentId)
  return { focus: parent?.node.id ?? id, expanded }
}

/** `*`: opens every sibling of the node. */
function openSiblings<T>(rows: readonly VisibleRow<T>[], current: VisibleRow<T>, expanded: ReadonlySet<string>): TreeAction {
  const siblings = rows.filter((row) => row.parentId === current.parentId && row.node.children.length > 0)
  return { focus: current.node.id, expanded: new Set([...expanded, ...siblings.map((row) => row.node.id)]) }
}

/** The next visible node whose label starts with the typed character, wrapping round. */
function nextStartingWith<T>(rows: readonly VisibleRow<T>[], index: number, key: string): VisibleRow<T> | undefined {
  const wanted = key.toLocaleLowerCase()
  const after = [...rows.slice(index + 1), ...rows.slice(0, index + 1)]
  return after.find((row) => row.node.label.toLocaleLowerCase().startsWith(wanted))
}
