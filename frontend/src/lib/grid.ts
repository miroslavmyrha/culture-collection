/** A position in a grid, counted from 0: row 0, column 0 is the top left cell. */
export type GridPos = { row: number; col: number }
export type GridSize = { rows: number; cols: number }

const clamp = (n: number, max: number) => Math.min(Math.max(n, 0), max)

/**
 * Where a key moves the focus in a grid (WAI-ARIA APG grid pattern), or null for a key the grid
 * does not handle. Arrows stop at the edges, they never wrap. Home and End go to the ends of the
 * row, with Ctrl (or Cmd) to the first and last cell. PageUp and PageDown go to the first and the
 * last row: a box is short enough to show whole.
 */
export function moveFocus(pos: GridPos, key: string, size: GridSize, ctrl = false): GridPos | null {
  const lastRow = size.rows - 1
  const lastCol = size.cols - 1
  switch (key) {
    case 'ArrowUp':
      return { ...pos, row: clamp(pos.row - 1, lastRow) }
    case 'ArrowDown':
      return { ...pos, row: clamp(pos.row + 1, lastRow) }
    case 'ArrowLeft':
      return { ...pos, col: clamp(pos.col - 1, lastCol) }
    case 'ArrowRight':
      return { ...pos, col: clamp(pos.col + 1, lastCol) }
    case 'Home':
      return ctrl ? { row: 0, col: 0 } : { ...pos, col: 0 }
    case 'End':
      return ctrl ? { row: lastRow, col: lastCol } : { ...pos, col: lastCol }
    case 'PageUp':
      return { ...pos, row: 0 }
    case 'PageDown':
      return { ...pos, row: lastRow }
    default:
      return null
  }
}

/** A position inside the size: the same one, or the nearest that still exists. */
export const clampPos = (pos: GridPos, size: GridSize): GridPos => ({
  row: clamp(pos.row, Math.max(size.rows - 1, 0)),
  col: clamp(pos.col, Math.max(size.cols - 1, 0)),
})

export const samePos = (a: GridPos | null, b: GridPos | null) => a !== null && b !== null && a.row === b.row && a.col === b.col
