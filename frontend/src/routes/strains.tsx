import { createRoute, lazyRouteComponent, stripSearchParams } from '@tanstack/react-router'
import { labDetailOptions } from '@/features/labs/api/queries'
import { strainDetailOptions, strainHistoryOptions, strainListOptions, strainTermsOptions } from '@/features/strains/api/queries'
import { strainListDefaults, strainListSearch } from '@/features/strains/schemas'
import { batchesOptions, passagesOptions, vialsOptions } from '@/features/vials/api/queries'
import { pageDefaults, pageSearch } from '@/lib/paging'
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

// One strain (#19): the header and the tab links around the open tab. Each tab is its own URL
// and its loader prefetches only that tab's data.
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

export const strainOverviewRoute = createRoute({
  getParentRoute: () => strainDetailRoute,
  path: '/',
  loader: ({ context, params }) => context.queryClient.prefetchQuery(strainTermsOptions(params.labId, params.strainId)),
  component: lazyRouteComponent(() => import('@/pages/StrainDetailPage'), 'StrainOverviewPage'),
})

export const strainMaterialRoute = createRoute({
  getParentRoute: () => strainDetailRoute,
  path: 'material',
  loader: ({ context, params }) =>
    Promise.all([
      context.queryClient.prefetchQuery(passagesOptions(params.labId, params.strainId)),
      context.queryClient.prefetchQuery(batchesOptions(params.labId, params.strainId)),
      context.queryClient.prefetchQuery(vialsOptions(params.labId, params.strainId)),
    ]),
  component: lazyRouteComponent(() => import('@/pages/StrainDetailPage'), 'StrainMaterialPage'),
})

export const strainTermsRoute = createRoute({
  getParentRoute: () => strainDetailRoute,
  path: 'terms',
  loader: ({ context, params }) => context.queryClient.prefetchQuery(strainTermsOptions(params.labId, params.strainId)),
  component: lazyRouteComponent(() => import('@/pages/StrainDetailPage'), 'StrainTermsPage'),
})

export const strainHistoryRoute = createRoute({
  getParentRoute: () => strainDetailRoute,
  path: 'history',
  validateSearch: pageSearch,
  search: { middlewares: [stripSearchParams(pageDefaults)] },
  loaderDeps: ({ search }) => search,
  loader: ({ context, params, deps }) => context.queryClient.prefetchQuery(strainHistoryOptions(params.labId, params.strainId, deps)),
  component: lazyRouteComponent(() => import('@/pages/StrainDetailPage'), 'StrainHistoryPage'),
})
