import { Box, Table, TableBody, TableCell, TableHead, TableRow } from '@mui/material'
import { type KeyboardEvent, type ReactNode, type Ref, useImperativeHandle, useLayoutEffect, useRef, useState } from 'react'
import { clampPos, type GridPos, moveFocus, samePos } from '@/lib/grid'

export type GridCell = {
  /** The accessible name: "A1, empty", "B3, MYC 42 / 1 / 3, available". State is never colour alone. */
  name: string
  content?: ReactNode
  /** Taken positions are drawn filled; a masked one is taken without saying by what. */
  tone: 'empty' | 'taken' | 'masked'
  selected?: boolean
  /** Activating it would be refused: aria-disabled, the cell keeps its place in the arrow order. */
  disabled?: boolean
}

export type PositionGridHandle = {
  /** Make a position the tab stop and focus it (after a cancelled move, after finding a vial). */
  focus: (pos: GridPos) => void
}

type Props = {
  /** The grid's name, "Box 1". */
  label: string
  rows: number
  cols: number
  cell: (pos: GridPos) => GridCell
  /** Enter, Space or a click on a position. Without it the grid is read only: no selection. */
  onActivate?: (pos: GridPos) => void
  /** Escape inside the grid. */
  onEscape?: () => void
  /** The position that holds the tab stop changed (by a key, a click or focus()). */
  onActiveChange?: (pos: GridPos) => void
  ref?: Ref<PositionGridHandle>
}

/** Rows as letters, columns as numbers, both from 1 for people: row 0, column 0 is A1. */
export const gridLabel = ({ row, col }: GridPos) => `${String.fromCodePoint(65 + row)}${col + 1}`

/**
 * A box of positions as an ARIA grid (WAI-ARIA APG, data grid): one tab stop, the arrows, Home,
 * End, Ctrl+Home, Ctrl+End, PageUp and PageDown move between positions, Enter and Space activate
 * one, and a click does the same. Focus follows state: a key sets the position, and a layout
 * effect moves DOM focus after the render. A focus event (a click, a tab into the grid) moves
 * the tab stop to where focus is. aria-selected marks the chosen position only, never the
 * focused one.
 *
 * The cell sizes keep every position at least 24 by 24 CSS px (WCAG 2.5.8). On a narrow screen
 * the grid scrolls inside its own container; the page does not.
 */
export function PositionGrid({ label, rows, cols, cell, onActivate, onEscape, onActiveChange, ref }: Props) {
  const tableRef = useRef<HTMLTableElement>(null)
  const [stored, setStored] = useState<GridPos>({ row: 0, col: 0 })
  // A box that changed its size keeps the tab stop on a position that exists.
  const active = clampPos(stored, { rows, cols })
  const pendingFocus = useRef(false) // DOM focus moves only after a key or focus() moved the state
  const readOnly = onActivate === undefined

  const setActive = (pos: GridPos) => {
    setStored(pos)
    onActiveChange?.(pos)
  }

  useLayoutEffect(() => {
    if (!pendingFocus.current) return
    pendingFocus.current = false
    tableRef.current?.querySelector<HTMLElement>(`[data-pos="${gridLabel(active)}"]`)?.focus()
  })

  useImperativeHandle(ref, () => ({
    focus: (pos: GridPos) => {
      pendingFocus.current = true
      setActive(clampPos(pos, { rows, cols }))
    },
  }))

  function onKeyDown(event: KeyboardEvent<HTMLTableElement>) {
    if (!(event.target instanceof HTMLElement) || event.target.getAttribute('role') !== 'gridcell') return
    if (event.key === 'Escape') {
      if (!onEscape) return
      event.preventDefault()
      onEscape()
      return
    }
    if (event.key === 'Enter' || event.key === ' ') {
      if (!onActivate) return
      event.preventDefault()
      onActivate(active)
      return
    }
    const next = moveFocus(active, event.key, { rows, cols }, event.ctrlKey || event.metaKey)
    if (next === null) return
    event.preventDefault() // the page must not scroll under the arrows
    pendingFocus.current = true
    setActive(next)
  }

  const rowIndexes = Array.from({ length: rows }, (_, i) => i)
  const colIndexes = Array.from({ length: cols }, (_, i) => i)
  return (
    // Scrolls sideways inside itself on a narrow screen. No tab stop of its own: the grid in it
    // always has one, so the arrows reach every position (WCAG 2.1.1).
    <Box sx={{ overflowX: 'auto', maxWidth: '100%' }}>
      <Table
        ref={tableRef}
        role="grid"
        aria-label={label}
        aria-readonly={readOnly || undefined}
        size="small"
        onKeyDown={onKeyDown}
        sx={{ width: 'auto', borderCollapse: 'separate', borderSpacing: 0 }}
      >
        <TableHead>
          <TableRow>
            <TableCell component="td" sx={{ border: 0 }} />
            {colIndexes.map((col) => (
              <TableCell key={col} scope="col" align="center" sx={{ border: 0, px: 0.5, py: 0.5, fontWeight: 'bold' }}>
                {col + 1}
              </TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {rowIndexes.map((row) => (
            <TableRow key={row}>
              <TableCell component="th" scope="row" sx={{ border: 0, px: 1, py: 0, fontWeight: 'bold', textAlign: 'center' }}>
                {String.fromCodePoint(65 + row)}
              </TableCell>
              {colIndexes.map((col) => {
                const pos = { row, col }
                const c = cell(pos)
                const isActive = samePos(pos, active)
                return (
                  <TableCell
                    key={col}
                    // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- explicit: jsdom and aria-query map td to cell, not gridcell
                    role="gridcell"
                    data-pos={gridLabel(pos)}
                    data-tone={c.tone}
                    tabIndex={isActive ? 0 : -1}
                    aria-label={c.name}
                    aria-selected={readOnly ? undefined : (c.selected ?? false)}
                    aria-disabled={c.disabled || undefined}
                    onFocus={() => {
                      if (!isActive) setActive(pos)
                    }}
                    onClick={onActivate ? () => onActivate(pos) : undefined}
                    sx={CELL}
                  >
                    {c.content}
                  </TableCell>
                )
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  )
}

/**
 * Light and dark come from the theme's variables. Every boundary and state is 3:1 or more against
 * what is next to it, measured in e2e/grid.spec.ts: the cell border (text.secondary), the selected
 * fill (primary.main against the paper), the focus ring (primary.main on a cell, the primary text
 * colour on the selected fill). An inset ring, so a neighbour cannot cover it.
 */
const CELL = {
  minWidth: '4.75rem',
  height: '3.25rem',
  boxSizing: 'border-box',
  p: 0.5,
  border: '1px solid',
  borderColor: 'text.secondary',
  textAlign: 'center',
  verticalAlign: 'middle',
  lineHeight: 1.25,
  fontSize: '0.8125rem',
  overflowWrap: 'anywhere',
  '&[aria-selected]': { cursor: 'pointer' },
  '&[aria-disabled="true"]': { cursor: 'not-allowed' },
  '&[data-tone="taken"]': { bgcolor: 'action.hover' },
  '&[data-tone="masked"]': { bgcolor: 'action.hover', color: 'text.secondary', fontStyle: 'italic' },
  '&[aria-selected="true"]': { bgcolor: 'primary.main', color: 'primary.contrastText', fontWeight: 'bold', fontStyle: 'normal' },
  '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: '-2px' },
  '&[aria-selected="true"]:focus-visible': { outlineColor: 'primary.contrastText' },
} as const
