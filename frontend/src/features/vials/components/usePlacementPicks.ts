import { useState } from 'react'
import { gridLabel } from '@/components/ui'
import type { GridPos } from '@/lib/grid'
import type { Vial } from '../schemas'
import { POSITION_TAKEN } from '../vialErrors'
import { keyOf, planOf } from './placement'

type Options = {
  vials: readonly Vial[]
  taken: ReadonlyMap<string, unknown>
  rows: number
  cols: number
  /** The request is on its way: the grid answers nothing. */
  locked: boolean
  /** A vial was given a position of the person's choice. */
  onPick: () => void
}

/**
 * The person's choices on the grid of the box: which vial is up next, which positions were picked
 * for which vial, what was last said, and the plan that follows (a pick first, the rest in fill order).
 */
export function usePlacementPicks({ vials, taken, rows, cols, locked, onPick }: Options) {
  const [picks, setPicks] = useState<ReadonlyMap<string, GridPos>>(new Map())
  const [current, setCurrent] = useState(0)
  const [message, setMessage] = useState('')
  const plan = planOf(vials, picks, taken, rows, cols)
  const planned = new Map([...plan.entries()].map(([vialId, pos]) => [keyOf(pos), vialId]))
  const currentVial = vials[current] ?? vials[0]

  /** A position picked for another vial: that vial becomes the one to move. */
  function takeOver(vialId: string, here: string) {
    const index = vials.findIndex((v) => v.public_id === vialId)
    setCurrent(index)
    setMessage(`${vials[index]?.label ?? ''} in ${here} chosen. Choose a free position for it.`)
  }

  /** A vial that had this position only by fill order moves on to the next free one. */
  function pick(vial: Vial, pos: GridPos, here: string) {
    setPicks((before) => new Map(before).set(vial.public_id, pos))
    onPick()
    setMessage(`${vial.label} goes to ${here}.`)
    setCurrent((current + 1) % vials.length)
  }

  function activate(pos: GridPos) {
    if (locked || currentVial === undefined) return
    if (taken.has(keyOf(pos))) return setMessage(POSITION_TAKEN)
    const other = planned.get(keyOf(pos))
    if (other !== undefined && other !== currentVial.public_id && picks.has(other)) return takeOver(other, gridLabel(pos))
    pick(currentVial, pos, gridLabel(pos))
  }

  return {
    picks,
    plan,
    planned,
    current,
    currentVial,
    message,
    activate,
    chooseVial: setCurrent,
    /** A new box: nothing was picked for it. */
    reset: () => {
      setPicks(new Map())
      setCurrent(0)
      setMessage('')
    },
    /** "Next free positions": the picks are dropped and the plan goes back to fill order. */
    dropPicks: () => {
      setPicks(new Map())
      setMessage('Each vial goes to the next free position.')
    },
  }
}
