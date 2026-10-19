import { queryOptions, useQuery } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import { boxTypeKeys, storageKeys } from './keys'

/** One options object for the hook, the route loader and typed cache access in tests. */
export const unitTreeOptions = (labId: string) =>
  queryOptions({
    queryKey: storageKeys.tree(labId),
    // The whole tree of the lab in one response, in tree order (ADR 0008, D14).
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/labs/{lab_public_id}/storage-units/', { signal, params: { path: { lab_public_id: labId } } })),
  })

export const unitDetailOptions = (labId: string, unitId: string) =>
  queryOptions({
    queryKey: storageKeys.detail(labId, unitId),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/labs/{lab_public_id}/storage-units/{public_id}/', {
          signal,
          params: { path: { lab_public_id: labId, public_id: unitId } },
        }),
      ),
  })

/** Staff add box types now and then: one page of the most there are is all of them. */
export const boxTypesOptions = () =>
  queryOptions({
    queryKey: boxTypeKeys.all,
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/box-types/', { signal, params: { query: { limit: 200 } } })),
    staleTime: 60_000,
  })

export function useUnitTree(labId: string) {
  return useQuery(unitTreeOptions(labId))
}

export function useUnit(labId: string, unitId: string) {
  return useQuery(unitDetailOptions(labId, unitId))
}

export function useBoxTypes(enabled = true) {
  return useQuery({ ...boxTypesOptions(), enabled })
}
