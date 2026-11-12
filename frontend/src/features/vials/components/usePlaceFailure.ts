import { useState } from 'react'
import { ApiError } from '@/lib/api'
import type { GridPos } from '@/lib/grid'
import type { Vial } from '../schemas'
import { gridError } from '../vialErrors'
import { keyOf, refusalOf } from './placement'
import type { Refused } from './PlaceVialsParts'

/**
 * What went wrong with a placement. A refusal names its vial and the position it was refused at:
 * once the plan moves the vial (a position taken meanwhile, refetched), the refusal no longer
 * describes it. Any other refusal is the line under the form.
 */
export function usePlaceFailure(vials: readonly Vial[], refetchGrid: () => void) {
  const [failure, setFailure] = useState<string>()
  const [failed, setFailed] = useState<Refused>()
  return {
    failure,
    failed,
    setFailure,
    dropRefusal: () => setFailed(undefined),
    clear: () => {
      setFailure(undefined)
      setFailed(undefined)
    },
    /** The vial a refusal names is marked at its position; any other refusal is the line under the form. */
    refuse: (error: unknown, plan: ReadonlyMap<string, GridPos>) => {
      const refusal = refusalOf(error, vials)
      if (refusal) {
        const at = plan.get(refusal.vial.public_id)
        setFailed({ vialId: refusal.vial.public_id, text: refusal.text, at: at ? keyOf(at) : '' })
        setFailure(`Vial ${refusal.vial.label}: ${refusal.text}`)
      } else setFailure(gridError(error))
      // A position someone took meanwhile shows as taken, and the plan moves around it.
      if (error instanceof ApiError && error.code === 'position_taken') refetchGrid()
    },
  }
}
