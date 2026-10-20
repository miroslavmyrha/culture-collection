import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { components } from '@/api/schema'
import { api, ensureCsrf, unwrap } from '@/lib/api'
import { vialKeys } from './keys'

type Schemas = components['schemas']

// Each dialog shows its own failure (meta.handlesError), so the global message stays quiet.
// onSuccess returns the invalidation of the strain's material and of the box grids (a vial may
// enter or leave a box): the mutation stays pending until the lists are fresh, so a dialog
// closes on data that already shows the change.
function useStrainWrite<T, R>(labId: string, strainId: string, write: (input: T) => Promise<R>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: T) => {
      await ensureCsrf()
      return write(input)
    },
    meta: { handlesError: true },
    onSuccess: () =>
      Promise.all([qc.invalidateQueries({ queryKey: vialKeys.strain(labId, strainId) }), qc.invalidateQueries({ queryKey: vialKeys.boxGrids(labId) })]),
  })
}

const lab = (labId: string) => ({ path: { lab_public_id: labId } })
const vial = (labId: string, vialId: string) => ({ path: { lab_public_id: labId, public_id: vialId } })

export function usePreserve(labId: string, strainId: string) {
  return useStrainWrite(labId, strainId, (body: Schemas['PreserveInputRequest']) =>
    unwrap(api.POST('/api/v1/labs/{lab_public_id}/batches/', { params: lab(labId), body })),
  )
}

export function useSubculture(labId: string, strainId: string) {
  return useStrainWrite(labId, strainId, (sourcePassage: string) =>
    unwrap(api.POST('/api/v1/labs/{lab_public_id}/passages/', { params: lab(labId), body: { source_passage: sourcePassage } })),
  )
}

export function usePlace(labId: string, strainId: string) {
  return useStrainWrite(labId, strainId, ({ vialId, ...body }: Schemas['PlaceInputRequest'] & { vialId: string }) =>
    unwrap(api.POST('/api/v1/labs/{lab_public_id}/vials/{public_id}/place/', { params: vial(labId, vialId), body })),
  )
}

export function useSetVialStatus(labId: string, strainId: string) {
  return useStrainWrite(labId, strainId, ({ vialId, ...body }: Schemas['VialStatusInputRequest'] & { vialId: string }) =>
    unwrap(api.POST('/api/v1/labs/{lab_public_id}/vials/{public_id}/status/', { params: vial(labId, vialId), body })),
  )
}

export function useRevive(labId: string, strainId: string) {
  return useStrainWrite(labId, strainId, (vialId: string) =>
    unwrap(api.POST('/api/v1/labs/{lab_public_id}/vials/{public_id}/revive/', { params: vial(labId, vialId) })),
  )
}

/**
 * Reveals where a vial of a regulated strain is (ADR 0009). Each call is a new request and a new
 * entry in the audit trail; the answer stays in the component that asked, never in the cache.
 */
export function useRevealLocation(labId: string) {
  return useMutation({
    mutationFn: async (vialId: string) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/vials/{public_id}/reveal-location/', { params: vial(labId, vialId) }))
    },
    meta: { handlesError: true },
  })
}

/**
 * Places or moves a vial from the box grid (the same place action as the strain page). Pending
 * until the lab's vial data is fresh, so the grid shows the vial in its new position when the
 * result is announced.
 */
export function useGridPlace(labId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ vialId, ...body }: Schemas['PlaceInputRequest'] & { vialId: string }) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/vials/{public_id}/place/', { params: vial(labId, vialId), body }))
    },
    meta: { handlesError: true },
    onSuccess: () => qc.invalidateQueries({ queryKey: vialKeys.lab(labId) }),
  })
}

/**
 * Finds a vial of the lab by its barcode or its label, as a scanner (which types like a
 * keyboard) or a person enters it. A lookup the person asked for, so a mutation: nothing is
 * cached and each Find asks the server again.
 */
export function useFindVial(labId: string) {
  return useMutation({
    mutationFn: (code: string) =>
      unwrap(api.GET('/api/v1/labs/{lab_public_id}/vials/', { params: { path: { lab_public_id: labId }, query: { code, limit: 2 } } })),
    meta: { handlesError: true },
  })
}
