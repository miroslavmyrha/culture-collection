import { keepPreviousData, queryOptions, useQuery } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import type { PageParams } from '../schemas'
import { labKeys } from './keys'

/** One options object for the hook, the route loader and typed cache access in tests. */
export const labListOptions = (params: PageParams) =>
  queryOptions({
    queryKey: labKeys.list(params),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/labs/', { signal, params: { query: params } })),
    // The previous page stays on screen while the next one loads.
    placeholderData: keepPreviousData,
  })

export const labDetailOptions = (labId: string) =>
  queryOptions({
    queryKey: labKeys.detail(labId),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/labs/{public_id}/', { signal, params: { path: { public_id: labId } } })),
  })

export const memberListOptions = (labId: string, params: PageParams) =>
  queryOptions({
    queryKey: labKeys.memberList(labId, params),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/labs/{lab_public_id}/members/', { signal, params: { path: { lab_public_id: labId }, query: params } })),
    placeholderData: keepPreviousData,
  })

export function useLabList(params: PageParams) {
  return useQuery(labListOptions(params))
}

export function useLab(labId: string) {
  return useQuery(labDetailOptions(labId))
}

export function useMemberList(labId: string, params: PageParams) {
  return useQuery(memberListOptions(labId, params))
}

export const locationGrantsOptions = (labId: string) =>
  queryOptions({
    queryKey: labKeys.locationGrants(labId),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/labs/{lab_public_id}/location-grants/', { signal, params: { path: { lab_public_id: labId } } })),
  })

/** Only managers read the grants: for anybody else the request is not even sent. */
export function useLocationGrants(labId: string, enabled: boolean) {
  return useQuery({ ...locationGrantsOptions(labId), enabled })
}
