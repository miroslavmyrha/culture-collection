import { keepPreviousData, queryOptions, useQuery } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import type { RequesterListParams, RequestListParams } from '../schemas'
import { requesterKeys, requestKeys, shipmentDocumentKeys, strainChoiceKeys } from './keys'

/** One options object for the hook, the route loader and typed cache access in tests. */
export const requestListOptions = (labId: string, params: RequestListParams) =>
  queryOptions({
    queryKey: requestKeys.list(labId, params),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/labs/{lab_public_id}/requests/', { signal, params: { path: { lab_public_id: labId }, query: params } })),
    placeholderData: keepPreviousData,
  })

export const requestDetailOptions = (labId: string, requestId: string) =>
  queryOptions({
    queryKey: requestKeys.detail(labId, requestId),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/labs/{lab_public_id}/requests/{public_id}/', { signal, params: { path: { lab_public_id: labId, public_id: requestId } } }),
      ),
  })

export const requesterListOptions = (labId: string, params: RequesterListParams) =>
  queryOptions({
    queryKey: requesterKeys.list(labId, params),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/labs/{lab_public_id}/requesters/', { signal, params: { path: { lab_public_id: labId }, query: params } })),
    placeholderData: keepPreviousData,
  })

/** A lab has few requesters: the form's select reads one page of 200. */
export const ALL_REQUESTERS = { limit: 200, offset: 0, search: undefined }

export const strainChoicesOptions = (labId: string, search: string) =>
  queryOptions({
    queryKey: strainChoiceKeys.search(labId, search),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/labs/{lab_public_id}/strains/', { signal, params: { path: { lab_public_id: labId }, query: { limit: 20, offset: 0, search } } }),
      ),
    placeholderData: keepPreviousData,
  })

/** Stored once and never changed (#90): it is not refetched while cached. */
export const shipmentDocumentOptions = (labId: string, documentId: string) =>
  queryOptions({
    queryKey: shipmentDocumentKeys.detail(labId, documentId),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/labs/{lab_public_id}/shipment-documents/{public_id}/', {
          signal,
          params: { path: { lab_public_id: labId, public_id: documentId } },
        }),
      ),
    staleTime: Infinity,
  })

export const useRequestList = (labId: string, params: RequestListParams) => useQuery(requestListOptions(labId, params))
export const useRequest = (labId: string, requestId: string) => useQuery(requestDetailOptions(labId, requestId))
export const useRequesterList = (labId: string, params: RequesterListParams, enabled = true) => useQuery({ ...requesterListOptions(labId, params), enabled })
export const useStrainChoices = (labId: string, search: string, enabled: boolean) => useQuery({ ...strainChoicesOptions(labId, search), enabled })
export const useShipmentDocument = (labId: string, documentId: string) => useQuery(shipmentDocumentOptions(labId, documentId))
