import { createRoute, lazyRouteComponent, stripSearchParams } from '@tanstack/react-router'
import { ALL_REQUESTERS, requestDetailOptions, requesterListOptions, requestListOptions } from '@/features/distribution/api/queries'
import { requesterListDefaults, requesterListSearch, requestListDefaults, requestListSearch } from '@/features/distribution/schemas'
import { labDetailOptions } from '@/features/labs/api/queries'
import { authenticatedRoute } from './authenticated'

// Requests and requesters of one lab, under the authenticated layout. The loaders prefetch with
// the components' own options and never throw: a lab the caller is not in (404) and a role that
// may not see these (403) are states of the page.

export const requestListRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId/requests',
  validateSearch: requestListSearch,
  search: { middlewares: [stripSearchParams(requestListDefaults)] },
  loaderDeps: ({ search }) => search,
  loader: ({ context, params, deps }) =>
    Promise.all([context.queryClient.prefetchQuery(labDetailOptions(params.labId)), context.queryClient.prefetchQuery(requestListOptions(params.labId, deps))]),
  component: lazyRouteComponent(() => import('@/pages/RequestListPage'), 'RequestListPage'),
})

export const requestNewRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId/requests/new',
  loader: ({ context, params }) =>
    Promise.all([context.queryClient.prefetchQuery(labDetailOptions(params.labId)), context.queryClient.prefetchQuery(requesterListOptions(params.labId, ALL_REQUESTERS))]),
  component: lazyRouteComponent(() => import('@/pages/RequestNewPage'), 'RequestNewPage'),
})

export const requestDetailRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId/requests/$requestId',
  loader: ({ context, params }) =>
    Promise.all([
      context.queryClient.prefetchQuery(labDetailOptions(params.labId)),
      context.queryClient.prefetchQuery(requestDetailOptions(params.labId, params.requestId)),
    ]),
  component: lazyRouteComponent(() => import('@/pages/RequestDetailPage'), 'RequestDetailPage'),
})

export const requesterListRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId/requesters',
  validateSearch: requesterListSearch,
  search: { middlewares: [stripSearchParams(requesterListDefaults)] },
  loaderDeps: ({ search }) => search,
  loader: ({ context, params, deps }) =>
    Promise.all([context.queryClient.prefetchQuery(labDetailOptions(params.labId)), context.queryClient.prefetchQuery(requesterListOptions(params.labId, deps))]),
  component: lazyRouteComponent(() => import('@/pages/RequesterListPage'), 'RequesterListPage'),
})
