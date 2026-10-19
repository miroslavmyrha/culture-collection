import { type KeyboardEvent, type MouseEvent, useId, useRef, useState } from 'react'
import { Box, Typography } from '@/components/ui'
import { KIND_WORDS, type UnitRow, unitSummary } from '../schemas'
import { buildTree, treeKey, type TreeNode, visibleRows } from '../treeModel'

type Props = {
  /** The tree's accessible name: "Storage of Mycology". */
  label: string
  rows: readonly UnitRow[]
  /** Enter or a click on a unit: show it. */
  onOpen: (unitId: string) => void
}

/** Siblings by slot (units without one last), then by name. */
const bySlotThenName = (a: UnitRow, b: UnitRow) => (a.slot ?? Infinity) - (b.slot ?? Infinity) || a.name.localeCompare(b.name)

/**
 * The storage of a lab as a tree (WAI-ARIA APG, Tree View): one tab stop, the arrow keys move
 * and open or close units, Home and End go to the first and last, a letter to the next unit
 * with that initial, Enter shows the focused unit. Freezers and tanks start open, so their
 * racks show at once. Each item is named by its label alone (aria-labelledby): the name from
 * content of a tree item would read the whole subtree below it.
 *
 * Own code rather than MUI X Tree View: that is a new dependency not yet checked under our
 * CSP, and the keyboard model fits in treeModel.ts, where it is tested without the DOM.
 */
export function StorageTree({ label, rows, onOpen }: Props) {
  const roots = buildTree(rows, bySlotThenName)
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set(roots.map((root) => root.id)))
  const [focusedId, setFocusedId] = useState<string | null>(null)
  const items = useRef(new Map<string, HTMLLIElement>())
  const hintId = useId()
  const visible = visibleRows(roots, expanded)
  // The remembered node, or the first one when it is gone (a refetch, a parent closed by a click).
  const focused = visible.find((row) => row.node.id === focusedId)?.node.id ?? visible[0]?.node.id

  const onKeyDown = (event: KeyboardEvent<HTMLUListElement>) => {
    if (focused === undefined || event.altKey || event.ctrlKey || event.metaKey) return
    const action = treeKey(visible, focused, event.key, expanded)
    if (action === null) return
    event.preventDefault()
    setExpanded(action.expanded)
    if (action.activate) {
      onOpen(focused)
      return
    }
    setFocusedId(action.focus)
    items.current.get(action.focus)?.focus()
  }

  const toggle = (id: string) =>
    setExpanded((open) => {
      const next = new Set(open)
      if (!next.delete(id)) next.add(id)
      return next
    })

  const renderNode = (node: TreeNode<UnitRow>, level: number, position: number, setSize: number) => {
    const isOpen = expanded.has(node.id)
    const hasChildren = node.children.length > 0
    const labelId = `${hintId}-${node.id}`
    const onClick = (event: MouseEvent<HTMLLIElement>) => {
      event.stopPropagation() // the innermost item handles a click, not the ones around it
      setFocusedId(node.id)
      if (event.target instanceof Element && event.target.closest('[data-toggle]')) toggle(node.id)
      else onOpen(node.id)
    }
    return (
      <Box
        component="li"
        key={node.id}
        role="treeitem"
        aria-level={level}
        aria-posinset={position}
        aria-setsize={setSize}
        aria-expanded={hasChildren ? isOpen : undefined}
        aria-labelledby={labelId}
        tabIndex={node.id === focused ? 0 : -1}
        ref={(element: HTMLLIElement | null) => {
          if (element) items.current.set(node.id, element)
          else items.current.delete(node.id)
        }}
        onFocus={(event) => {
          if (event.target === event.currentTarget) setFocusedId(node.id)
        }}
        onClick={onClick}
        sx={{
          listStyle: 'none',
          outline: 'none',
          '&:focus-visible > div': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: -2 },
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1, py: 0.75, px: 1, cursor: 'pointer', borderRadius: 1, '&:hover': { bgcolor: 'action.hover' } }}>
          <Box component="span" data-toggle aria-hidden sx={{ width: '1em', flex: 'none', textAlign: 'center', color: 'text.secondary' }}>
            {hasChildren ? (isOpen ? '▾' : '▸') : ''}
          </Box>
          <Typography component="span" id={labelId} sx={{ overflowWrap: 'anywhere', color: node.item.status === 'active' ? 'text.primary' : 'text.secondary' }}>
            <Box component="span" sx={{ fontWeight: 'bold' }}>
              {node.label}
            </Box>
            , {unitSummary(node.item)}
          </Typography>
        </Box>
        {hasChildren && isOpen && (
          // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- the nested list of a tree is a group (WAI-ARIA APG, Tree View); no element has that role inside a tree
          <Box component="ul" role="group" aria-label={`In ${KIND_WORDS[node.item.kind]} ${node.label}`} sx={{ m: 0, pl: 3 }}>
            {node.children.map((child, index) => renderNode(child, level + 1, index + 1, node.children.length))}
          </Box>
        )}
      </Box>
    )
  }

  return (
    <>
      <Typography id={hintId} variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        Arrow keys move through the units and open or close them, Enter shows a unit.
      </Typography>
      <Box component="ul" role="tree" aria-label={label} aria-describedby={hintId} onKeyDown={onKeyDown} sx={{ m: 0, p: 0 }}>
        {roots.map((node, index) => renderNode(node, 1, index + 1, roots.length))}
      </Box>
    </>
  )
}
