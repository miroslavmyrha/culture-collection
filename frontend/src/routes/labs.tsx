import { createRoute, lazyRouteComponent, stripSearchParams } from '@tanstack/react-router'
import { labDetailOptions, labListOptions, memberListOptions } from '@/features/labs/api/queries'
import { pageDefaults, pageSearch } from '@/lib/paging'
import { authenticatedRoute } from './authenticated'

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
  loader: ({ context, deps }) => context.queryClient.prefetchQuery(labListOptions(deps)),
  component: lazyRouteComponent(() => import('@/pages/LabListPage'), 'LabListPage'),
})

export const labDetailRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId',
  validateSearch: pageSearch,
  search: { middlewares: [stripSearchParams(pageDefaults)] },
  loaderDeps: ({ search }) => search,
  loader: ({ context, params, deps }) =>
    Promise.all([
      context.queryClient.prefetchQuery(labDetailOptions(params.labId)),
      context.queryClient.prefetchQuery(memberListOptions(params.labId, deps)),
    ]),
  component: lazyRouteComponent(() => import('@/pages/LabDetailPage'), 'LabDetailPage'),
})
