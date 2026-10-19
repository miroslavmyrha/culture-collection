import { createRoute, lazyRouteComponent } from '@tanstack/react-router'
import { labDetailOptions } from '@/features/labs/api/queries'
import { unitDetailOptions, unitTreeOptions } from '@/features/storage/api/queries'
import { authenticatedRoute } from './authenticated'

// The storage of one lab, under the authenticated layout: the guard runs first, so anonymous
// users never fetch. The loaders prefetch with the components' own options and never throw:
// a lab or unit the user cannot see (404) is a state of the page, not a route error.

export const storageRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId/storage',
  loader: ({ context, params }) =>
    Promise.all([
      context.queryClient.prefetchQuery(labDetailOptions(params.labId)),
      context.queryClient.prefetchQuery(unitTreeOptions(params.labId)),
    ]),
  component: lazyRouteComponent(() => import('@/pages/StoragePage'), 'StoragePage'),
})

export const storageUnitRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId/storage/$unitId',
  loader: ({ context, params }) =>
    Promise.all([
      context.queryClient.prefetchQuery(labDetailOptions(params.labId)),
      context.queryClient.prefetchQuery(unitDetailOptions(params.labId, params.unitId)),
    ]),
  component: lazyRouteComponent(() => import('@/pages/StorageUnitPage'), 'StorageUnitPage'),
})
