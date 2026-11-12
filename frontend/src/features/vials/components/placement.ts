import { ApiError, readProblem } from '@/lib/api'
import { type GridCell, gridLabel } from '@/components/ui'
import type { GridPos } from '@/lib/grid'
import type { BoxPosition, Vial } from '../schemas'
import { entryError } from '../vialErrors'

export const keyOf = (pos: GridPos) => `${pos.row}:${pos.col}`

/** The positions of a box that hold a vial, by grid key. The grid counts from 1, the screen from 0. */
export function takenOf(positions: readonly BoxPosition[] | undefined): Map<string, BoxPosition> {
  return new Map((positions ?? []).map((p) => [keyOf({ row: p.row - 1, col: p.col - 1 }), p]))
}

/**
 * Where each vial goes: a picked position first, the others into the free positions in fill
 * order (row by row), skipping taken and picked ones. A vial without a free position is missing.
 */
export function planOf(vials: readonly Vial[], picks: ReadonlyMap<string, GridPos>, taken: ReadonlyMap<string, unknown>, rows: number, cols: number): Map<string, GridPos> {
  const plan = new Map<string, GridPos>()
  const used = new Set<string>(taken.keys())
  for (const v of vials) {
    const pos = picks.get(v.public_id)
    if (pos && !used.has(keyOf(pos))) {
      plan.set(v.public_id, pos)
      used.add(keyOf(pos))
    }
  }
  fillFree(vials, plan, used, rows, cols)
  return plan
}

/** The vials without a position go into the free ones in fill order, until the box is full. */
function fillFree(vials: readonly Vial[], plan: Map<string, GridPos>, used: Set<string>, rows: number, cols: number) {
  let row = 0
  let col = 0
  for (const v of vials) {
    if (plan.has(v.public_id)) continue
    while (row < rows && used.has(keyOf({ row, col }))) {
      col++
      if (col === cols) {
        col = 0
        row++
      }
    }
    if (row >= rows) return
    plan.set(v.public_id, { row, col })
    used.add(keyOf({ row, col }))
  }
}

/** The words for a box that cannot take every vial. */
export function noRoomText(free: number, count: number): string {
  return `This box has ${free} free ${free === 1 ? 'position' : 'positions'} for ${count} vials. Choose another box.`
}

/** What the grid shows at a position: taken (never by what, ADR 0009), a planned vial, or free. */
export function cellOf(pos: GridPos, taken: ReadonlyMap<string, unknown>, planned: ReadonlyMap<string, string>, vials: readonly Vial[], currentVial: Vial | undefined): GridCell {
  const here = gridLabel(pos)
  if (taken.has(keyOf(pos))) return { name: `${here}, taken`, tone: 'masked', content: 'Taken', disabled: true }
  const vial = vials.find((v) => v.public_id === planned.get(keyOf(pos)))
  if (vial) return { name: `${here}, ${vial.label}`, tone: 'taken', content: vial.label.split(' / ').slice(-2).join(' / '), selected: vial === currentVial }
  return { name: `${here}, free`, tone: 'empty', selected: false }
}

/** The request body: each vial at its planned position, counted from 1. */
export function placementsOf(vials: readonly Vial[], plan: ReadonlyMap<string, GridPos>) {
  return vials.map((v) => {
    const pos = plan.get(v.public_id) ?? { row: 0, col: 0 }
    return { vial: v.public_id, row: pos.row + 1, col: pos.col + 1 }
  })
}

/** The index in a `placements.<i>` attr, if the attr names one. */
const placementIndex = (attr: string | null | undefined) => /^placements\.(\d+)(\.|$)/.exec(attr ?? '')?.[1]

/** The vial a refusal is about, from its `placements.<i>` attr, and what it means. */
export function refusalOf(error: unknown, vials: readonly Vial[]): { vial: Vial; text: string } | undefined {
  if (!(error instanceof ApiError)) return undefined
  for (const e of readProblem(error.body)?.errors ?? []) {
    const index = placementIndex(e.attr)
    const vial = index === undefined ? undefined : vials[Number(index)]
    if (vial) return { vial, text: entryError(e.code || error.code || '') }
  }
  return undefined
}
