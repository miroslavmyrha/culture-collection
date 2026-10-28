import { keepPreviousData, queryOptions, useQuery } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import { storageUnitsOptions } from '@/lib/shared-keys'
import { boxChoices, type VialPage } from '../schemas'
import { vialKeys } from './keys'

// One page of the most the API gives: a strain's passages and batches fit in it, and so do the
// vials of one batch (at most 200). The count tells when they do not. The strain's vials are
// paged (vialPageOptions, #72).
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

/** A page of the strain's vials, by batch and number, with the count of all that match (#72). */
export const vialPageOptions = (labId: string, strainId: string, page: VialPage) =>
  queryOptions({
    queryKey: vialKeys.vialPage(labId, strainId, page),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/labs/{lab_public_id}/vials/', {
          signal,
          params: { path: { lab_public_id: labId }, query: { strain: strainId, limit: page.limit, offset: page.offset, ...(page.batch ? { batch: page.batch } : {}), ...(page.vial ? { vial: page.vial } : {}) } },
        }),
      ),
    // The page before stays on screen while the next one loads.
    placeholderData: keepPreviousData,
  })

/**
 * The vials reserved for a request with their places, in the order one walk through the storage
 * picks them up (#143). One answer, no pages: a request holds at most 20 lines of 50 vials.
 */
export const requestVialsOptions = (labId: string, requestId: string) =>
  queryOptions({
    queryKey: vialKeys.request(labId, requestId),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/labs/{lab_public_id}/requests/{public_id}/vials/', { signal, params: { path: { lab_public_id: labId, public_id: requestId } } })),
  })

export function useRequestVials(labId: string, requestId: string) {
  return useQuery(requestVialsOptions(labId, requestId))
}

/** Every vial of one batch (at most 200): what a check of the batch may name. */
export const batchVialsPage = (batchId: string): VialPage => ({ limit: MATERIAL_PAGE, offset: 0, batch: batchId })

/** Every check of one batch, newest first, entered in error included: a batch has few. */
export const checksOptions = (labId: string, strainId: string, batchId: string) =>
  queryOptions({
    queryKey: vialKeys.checks(labId, strainId, batchId),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/labs/{lab_public_id}/batch-checks/', { signal, params: { path: { lab_public_id: labId }, query: { batch: batchId, limit: MATERIAL_PAGE } } })),
  })

/** Loaded when the batch's checks are opened, not with the page. */
export function useBatchChecks(labId: string, strainId: string, batchId: string) {
  return useQuery(checksOptions(labId, strainId, batchId))
}

export function usePassages(labId: string, strainId: string) {
  return useQuery(passagesOptions(labId, strainId))
}

export function useBatches(labId: string, strainId: string) {
  return useQuery(batchesOptions(labId, strainId))
}

export function useVialPage(labId: string, strainId: string, page: VialPage, enabled = true) {
  return useQuery({ ...vialPageOptions(labId, strainId, page), enabled })
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
