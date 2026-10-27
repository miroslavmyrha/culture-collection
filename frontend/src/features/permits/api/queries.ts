import { queryOptions, useQuery } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import { permitKeys } from './keys'

/** One options object for the hook, the route loader and typed cache access in tests. */
export const permitListOptions = (labId: string) =>
  queryOptions({
    queryKey: permitKeys.list(labId),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/labs/{lab_public_id}/permits/', { signal, params: { path: { lab_public_id: labId } } })),
  })

/** The page mounts the list only for managers; the server refuses everyone else (403). */
export function usePermitList(labId: string) {
  return useQuery(permitListOptions(labId))
}
