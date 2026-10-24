import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query'
import type { components } from '@/api/schema'
import { api, ensureCsrf, unwrap } from '@/lib/api'
import { sharedKeys } from '@/lib/shared-keys'
import { strainKeys } from './keys'

type Schemas = components['schemas']
type Strain = Schemas['StrainDetailOutput']

// Each form and dialog shows its own failure (meta.handlesError), so the global message stays
// quiet. A write answers with the strain's detail: it goes into the cache as is, and the lab's
// lists are invalidated. So are the strain's material and the lab's box grids (shared keys): a
// restriction decides whether a vial's location shows, and the grids show the accession, the
// taxon and masked positions. The returned promise keeps the mutation pending until all are fresh.
function settle(qc: QueryClient, labId: string, strain: Strain) {
  qc.setQueryData(strainKeys.detail(labId, strain.public_id), strain)
  return Promise.all([
    qc.invalidateQueries({ queryKey: strainKeys.lists(labId) }),
    qc.invalidateQueries({ queryKey: sharedKeys.strainMaterial(labId, strain.public_id) }),
    qc.invalidateQueries({ queryKey: sharedKeys.boxGrids(labId) }),
  ])
}

const path = (labId: string, strainId: string) => ({ path: { lab_public_id: labId, public_id: strainId } })

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

type EndPath = { restrictionId: string }
const endPath = (labId: string, strainId: string, restrictionId: string) => ({
  path: { lab_public_id: labId, public_id: strainId, restriction_id: restrictionId },
})

/** The first of two steps (#105): nothing changes for the strain until a manager confirms. */
export function useProposeEnd(labId: string, strainId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ restrictionId, reason }: EndPath & { reason: string }) => {
      await ensureCsrf()
      return unwrap(
        api.POST('/api/v1/labs/{lab_public_id}/strains/{public_id}/restrictions/{restriction_id}/end-proposal/', {
          params: endPath(labId, strainId, restrictionId),
          body: { reason },
        }),
      )
    },
    meta: { handlesError: true },
    onSuccess: (strain) => settle(qc, labId, strain),
  })
}

/** The proposal the manager read, by its id: another one open meanwhile is a 409. */
export function useConfirmEnd(labId: string, strainId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ restrictionId, proposal }: EndPath & { proposal: string }) => {
      await ensureCsrf()
      return unwrap(
        api.POST('/api/v1/labs/{lab_public_id}/strains/{public_id}/restrictions/{restriction_id}/end-proposal/confirm/', {
          params: endPath(labId, strainId, restrictionId),
          body: { proposal },
        }),
      )
    },
    meta: { handlesError: true },
    onSuccess: (strain) => settle(qc, labId, strain),
  })
}

export function useWithdrawEnd(labId: string, strainId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ restrictionId, proposal, reason }: EndPath & { proposal: string; reason: string }) => {
      await ensureCsrf()
      return unwrap(
        api.POST('/api/v1/labs/{lab_public_id}/strains/{public_id}/restrictions/{restriction_id}/end-proposal/withdraw/', {
          params: endPath(labId, strainId, restrictionId),
          body: { proposal, reason },
        }),
      )
    },
    meta: { handlesError: true },
    onSuccess: (strain) => settle(qc, labId, strain),
  })
}
