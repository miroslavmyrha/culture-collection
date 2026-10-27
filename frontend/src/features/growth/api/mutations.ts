import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query'
import type { components } from '@/api/schema'
import { api, ensureCsrf, unwrap } from '@/lib/api'
import { sharedKeys } from '@/lib/shared-keys'

type Schemas = components['schemas']

// Each dialog shows its own failure (meta.handlesError). A medium shows by name on the strains
// and passages that use it, and by its retired mark: a write refreshes the lab's media, strains
// and material (shared keys). The promise keeps the mutation pending until they are fresh.
function settle(qc: QueryClient, labId: string) {
  return Promise.all([
    qc.invalidateQueries({ queryKey: sharedKeys.media(labId) }),
    qc.invalidateQueries({ queryKey: sharedKeys.strains(labId) }),
    qc.invalidateQueries({ queryKey: sharedKeys.material(labId) }),
  ])
}

const lab = (labId: string) => ({ path: { lab_public_id: labId } })
const one = (labId: string, mediumId: string) => ({ path: { lab_public_id: labId, public_id: mediumId } })

export function useCreateMedium(labId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['MediumInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/media/', { params: lab(labId), body }))
    },
    meta: { handlesError: true },
    onSuccess: () => settle(qc, labId),
  })
}

export function useUpdateMedium(labId: string, mediumId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['MediumInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.PUT('/api/v1/labs/{lab_public_id}/media/{public_id}/', { params: one(labId, mediumId), body }))
    },
    meta: { handlesError: true },
    onSuccess: () => settle(qc, labId),
  })
}

/** A medium is never deleted: retiring keeps it where it was used and stops new use. */
export function useRetireMedium(labId: string, mediumId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['MediumRetireInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/media/{public_id}/retire/', { params: one(labId, mediumId), body }))
    },
    meta: { handlesError: true },
    onSuccess: () => settle(qc, labId),
  })
}
