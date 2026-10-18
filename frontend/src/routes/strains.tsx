import { createRoute, lazyRouteComponent, stripSearchParams } from '@tanstack/react-router'
import { labDetailOptions } from '@/features/labs/api/queries'
import { strainDetailOptions, strainListOptions } from '@/features/strains/api/queries'
import { strainListDefaults, strainListSearch } from '@/features/strains/schemas'
import { authenticatedRoute } from './authenticated'

// The strains of one lab, under the authenticated layout: the guard runs first, so anonymous
// users never fetch. The loaders prefetch with the components' own options and never throw:
// a lab or strain the user cannot see (404) is a state of the page, not a route error.

export const strainListRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId/strains',
  validateSearch: strainListSearch,
  search: { middlewares: [stripSearchParams(strainListDefaults)] },
  loaderDeps: ({ search }) => search,
  loader: ({ context, params, deps }) =>
    Promise.all([
      context.queryClient.prefetchQuery(labDetailOptions(params.labId)),
      context.queryClient.prefetchQuery(strainListOptions(params.labId, deps)),
    ]),
  component: lazyRouteComponent(() => import('@/pages/StrainListPage'), 'StrainListPage'),
})

export const strainCreateRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId/strains/new',
  loader: ({ context, params }) => context.queryClient.prefetchQuery(labDetailOptions(params.labId)),
  component: lazyRouteComponent(() => import('@/pages/StrainCreatePage'), 'StrainCreatePage'),
})

export const strainDetailRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId/strains/$strainId',
  loader: ({ context, params }) =>
    Promise.all([
      context.queryClient.prefetchQuery(labDetailOptions(params.labId)),
      context.queryClient.prefetchQuery(strainDetailOptions(params.labId, params.strainId)),
    ]),
  component: lazyRouteComponent(() => import('@/pages/StrainDetailPage'), 'StrainDetailPage'),
})
