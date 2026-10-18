import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query'
import type { components } from '@/api/schema'
import { api, ensureCsrf, unwrap } from '@/lib/api'
import { strainKeys } from './keys'

type Schemas = components['schemas']
type Strain = Schemas['StrainDetailOutput']

// Each form and dialog shows its own failure (meta.handlesError), so the global message stays
// quiet. A write answers with the strain's detail: it goes into the cache as is, and the lab's
// lists are invalidated; the returned promise keeps the mutation pending until they are fresh.
function settle(qc: QueryClient, labId: string, strain: Strain) {
  qc.setQueryData(strainKeys.detail(labId, strain.public_id), strain)
  return qc.invalidateQueries({ queryKey: strainKeys.lists(labId) })
}

const path = (labId: string, strainId: string) => ({ path: { lab_public_id: labId, public_id: strainId } })

export function useCreateStrain(labId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['StrainCreateInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/strains/', { params: { path: { lab_public_id: labId } }, body }))
    },
    meta: { handlesError: true },
    onSuccess: (strain) => settle(qc, labId, strain),
  })
}

export function useReclassify(labId: string, strainId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['ReclassifyInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/strains/{public_id}/reclassify/', { params: path(labId, strainId), body }))
    },
    meta: { handlesError: true },
    onSuccess: (strain) => settle(qc, labId, strain),
  })
}

export function useSetRiskGroup(labId: string, strainId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['RiskGroupInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/strains/{public_id}/risk-group/', { params: path(labId, strainId), body }))
    },
    meta: { handlesError: true },
    onSuccess: (strain) => settle(qc, labId, strain),
  })
}

export function useAddRestriction(labId: string, strainId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['RestrictionAddInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/strains/{public_id}/restrictions/', { params: path(labId, strainId), body }))
    },
    meta: { handlesError: true },
    onSuccess: (strain) => settle(qc, labId, strain),
  })
}

export function useEndRestriction(labId: string, strainId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ restrictionId, reason }: { restrictionId: string; reason: string }) => {
      await ensureCsrf()
      return unwrap(
        api.POST('/api/v1/labs/{lab_public_id}/strains/{public_id}/restrictions/{restriction_id}/end/', {
          params: { path: { lab_public_id: labId, public_id: strainId, restriction_id: restrictionId } },
          body: { reason },
        }),
      )
    },
    meta: { handlesError: true },
    onSuccess: (strain) => settle(qc, labId, strain),
  })
}
