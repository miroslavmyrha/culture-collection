import { queryOptions, useQuery } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import { authKeys } from './keys'

/** The signed-in user, or null when anonymous. One options object for the hook, guards and tests. */
export const meQueryOptions = () =>
  queryOptions({
    queryKey: authKeys.me(),
    queryFn: async ({ signal }) => {
      const result = await api.GET('/api/v1/auth/me/', { signal })
      // 401 is the answer for anonymous requests; 403 is kept for backends that still send it.
      if (result.response.status === 401 || result.response.status === 403) return null
      return unwrap(result)
    },
    staleTime: 60_000,
  })

export function useMe() {
  return useQuery(meQueryOptions())
}
