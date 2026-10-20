import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query'
import type { components } from '@/api/schema'
import { api, ensureCsrf, unwrap } from '@/lib/api'
import { sharedKeys } from '@/lib/shared-keys'
import { storageKeys } from './keys'

type Schemas = components['schemas']
type Unit = Schemas['UnitDetailOutput']

// Each form and dialog shows its own failure (meta.handlesError). A write answers with the
// unit's detail: it goes into the cache as is, and the rest of the lab's storage is
// invalidated, the vials' box choices with it (the same entry as the tree). So is the lab's
// material (shared keys): vial locations and box grids show unit names, paths and sizes. The
// returned promise keeps the mutation pending until all of it is fresh.
function settle(qc: QueryClient, labId: string, unit: Unit) {
  qc.setQueryData(storageKeys.detail(labId, unit.public_id), unit)
  return Promise.all([
    qc.invalidateQueries({
      queryKey: storageKeys.lab(labId),
      predicate: (query) => query.queryKey[3] !== unit.public_id,
    }),
    qc.invalidateQueries({ queryKey: sharedKeys.material(labId) }),
  ])
}

const path = (labId: string, unitId: string) => ({ path: { lab_public_id: labId, public_id: unitId } })

export function useCreateUnit(labId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['UnitCreateInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/storage-units/', { params: { path: { lab_public_id: labId } }, body }))
    },
    meta: { handlesError: true },
    onSuccess: (unit) => settle(qc, labId, unit),
  })
}

export function useEditUnit(labId: string, unitId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['UnitFieldsInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/storage-units/{public_id}/edit/', { params: path(labId, unitId), body }))
    },
    meta: { handlesError: true },
    onSuccess: (unit) => settle(qc, labId, unit),
  })
}

export function useMoveUnit(labId: string, unitId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['UnitMoveInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/storage-units/{public_id}/move/', { params: path(labId, unitId), body }))
    },
    meta: { handlesError: true },
    onSuccess: (unit) => settle(qc, labId, unit),
  })
}

export function useSetUnitStatus(labId: string, unitId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['UnitStatusInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/storage-units/{public_id}/status/', { params: path(labId, unitId), body }))
    },
    meta: { handlesError: true },
    onSuccess: (unit) => settle(qc, labId, unit),
  })
}
