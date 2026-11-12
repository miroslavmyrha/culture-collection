import { useState } from 'react'
import { OUT_OF_A_BOX, type Vial } from '../schemas'

/**
 * The vials chosen to go into a box together (#77), by id. Only those on this page that are
 * still in no box count: a vial placed meanwhile drops out by itself.
 */
export function useVialSelection(rows: readonly Vial[] | undefined, canHandle: boolean) {
  const [chosen, setChosen] = useState<ReadonlySet<string>>(new Set())
  const placeable = (v: Vial) => canHandle && !v.placed && !OUT_OF_A_BOX.includes(v.status)
  const loose = (rows ?? []).filter(placeable)
  const selected = loose.filter((v) => chosen.has(v.public_id))
  const toggle = (vialId: string) =>
    setChosen((current) => {
      const next = new Set(current)
      if (!next.delete(vialId)) next.add(vialId)
      return next
    })
  const setAll = (all: boolean) => setChosen(new Set(all ? loose.map((v) => v.public_id) : []))
  const clear = () => setChosen(new Set())
  return { chosen, placeable, loose, selected, toggle, setAll, clear }
}

export type VialSelection = ReturnType<typeof useVialSelection>
