import { createRoute, lazyRouteComponent, stripSearchParams } from '@tanstack/react-router'
import { labDetailOptions, labListOptions, memberListOptions } from '@/features/labs/api/queries'
import { pageDefaults, pageSearch } from '@/lib/paging'
import { authenticatedRoute } from './authenticated'
import { prefetch, prefetchFor } from '@/lib/prefetch'

// Under the authenticated layout: the guard runs first, so anonymous users never fetch.
// The loaders prefetch with the components' own options and never throw: the feature
// components show loading, error with retry, empty and data themselves, and a lab the
// user is not a member of (404) is a state of the page, not a route error.

export const labListRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs',
  validateSearch: pageSearch,
  search: { middlewares: [stripSearchParams(pageDefaults)] },
  loaderDeps: ({ search }) => search,
  loader: ({ context, deps, cause }) => prefetchFor(cause, context.queryClient, labListOptions(deps)),
  component: lazyRouteComponent(() => import('@/pages/LabListPage'), 'LabListPage'),
})

export const labDetailRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId',
  validateSearch: pageSearch,
  search: { middlewares: [stripSearchParams(pageDefaults)] },
  loaderDeps: ({ search }) => search,
  loader: ({ context, params, deps, cause }) =>
    Promise.all([
      prefetch(context.queryClient, labDetailOptions(params.labId)),
      prefetchFor(cause, context.queryClient, memberListOptions(params.labId, deps)),
    ]),
  component: lazyRouteComponent(() => import('@/pages/LabDetailPage'), 'LabDetailPage'),
})

// The VRAT access list to print (#167). Only managers read it: the page loads the lab first and
// asks for the list and the permits only for a manager, so the loader prefetches the lab alone.
export const vratAccessRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId/vrat-access',
  loader: ({ context, params }) => prefetch(context.queryClient, labDetailOptions(params.labId)),
  component: lazyRouteComponent(() => import('@/pages/VratAccessPage'), 'VratAccessPage'),
})
