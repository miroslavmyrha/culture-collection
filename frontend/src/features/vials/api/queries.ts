import { queryOptions, useQuery } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import { storageUnitsOptions } from '@/lib/shared-keys'
import { boxChoices } from '../schemas'
import { vialKeys } from './keys'

// One page of the most the API gives: a strain's material fits in it (a batch has at most 200
// vials; the count tells when it does not).
export const MATERIAL_PAGE = 200

const strainQuery = (labId: string, strainId: string) => ({
  path: { lab_public_id: labId },
  query: { strain: strainId, limit: MATERIAL_PAGE },
})

export const passagesOptions = (labId: string, strainId: string) =>
  queryOptions({
    queryKey: vialKeys.passages(labId, strainId),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/labs/{lab_public_id}/passages/', { signal, params: strainQuery(labId, strainId) })),
  })

export const batchesOptions = (labId: string, strainId: string) =>
  queryOptions({
    queryKey: vialKeys.batches(labId, strainId),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/labs/{lab_public_id}/batches/', { signal, params: strainQuery(labId, strainId) })),
  })

export const vialsOptions = (labId: string, strainId: string) =>
  queryOptions({
    queryKey: vialKeys.vials(labId, strainId),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/labs/{lab_public_id}/vials/', { signal, params: strainQuery(labId, strainId) })),
  })

export function usePassages(labId: string, strainId: string) {
  return useQuery(passagesOptions(labId, strainId))
}

export function useBatches(labId: string, strainId: string) {
  return useQuery(batchesOptions(labId, strainId))
}

export function useVials(labId: string, strainId: string) {
  return useQuery(vialsOptions(labId, strainId))
}

/**
 * The lab's active boxes, named by their path, for the forms that place vials: the storage tree's
 * entry, so a storage write refreshes them. boxChoices is a module function, so select reruns only
 * when the units change.
 */
export function useBoxes(labId: string, enabled: boolean) {
  return useQuery({ ...storageUnitsOptions(labId), select: boxChoices, enabled })
}

/** A box with its taken positions; a regulated vial's position is masked and names no vial. */
export const boxGridOptions = (labId: string, boxId: string) =>
  queryOptions({
    queryKey: vialKeys.box(labId, boxId),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/labs/{lab_public_id}/boxes/{public_id}/', { signal, params: { path: { lab_public_id: labId, public_id: boxId } } })),
  })

export function useBoxGrid(labId: string, boxId: string) {
  return useQuery(boxGridOptions(labId, boxId))
}
