import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { components } from '@/api/schema'
import { api, ensureCsrf, unwrap } from '@/lib/api'
import { vialKeys } from './keys'

type Schemas = components['schemas']

// Each dialog shows its own failure (meta.handlesError), so the global message stays quiet.
// onSuccess returns the invalidation of the strain's material: the mutation stays pending until
// the lists are fresh, so a dialog closes on data that already shows the change.
function useStrainWrite<T, R>(labId: string, strainId: string, write: (input: T) => Promise<R>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: T) => {
      await ensureCsrf()
      return write(input)
    },
    meta: { handlesError: true },
    onSuccess: () => qc.invalidateQueries({ queryKey: vialKeys.strain(labId, strainId) }),
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
