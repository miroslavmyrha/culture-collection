import { keepPreviousData, queryOptions, useQuery } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import type { RevealListParams } from '../schemas'
import { revealKeys } from './keys'

/** One options object for the hook, the route loader and typed cache access in tests. */
export const revealListOptions = (labId: string, params: RevealListParams) =>
  queryOptions({
    queryKey: revealKeys.list(labId, params),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/labs/{public_id}/reveals/', { signal, params: { path: { public_id: labId }, query: params } })),
    placeholderData: keepPreviousData,
  })

/** The page mounts the list only for managers; the server refuses everyone else (403). */
export const useRevealList = (labId: string, params: RevealListParams) => useQuery(revealListOptions(labId, params))
