import { queryOptions, useQuery } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import { sharedKeys } from '@/lib/shared-keys'

export const homeKeys = {
  /** What waits, the labs' figures and actions: Home and the lab tabs read it (lib/shared-keys). */
  overview: sharedKeys.overview,
  activity: () => ['activity'] as const,
}

/** One options object for the hook, the route loader and the lab tabs. */
export const overviewOptions = () =>
  queryOptions({
    queryKey: homeKeys.overview(),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/me/overview/', { signal })),
  })

export const activityOptions = () =>
  queryOptions({
    queryKey: homeKeys.activity(),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/me/activity/', { signal })),
  })

export function useOverview() {
  return useQuery(overviewOptions())
}

export function useActivity() {
  return useQuery(activityOptions())
}
