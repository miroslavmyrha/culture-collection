import { createRoute, lazyRouteComponent, stripSearchParams } from '@tanstack/react-router'
import { depositDetailOptions, depositListOptions, depositorListOptions, mtaDetailOptions, mtaListOptions } from '@/features/deposits/api/queries'
import { depositListDefaults, depositListSearch, depositorListDefaults, depositorListSearch, mtaNewSearch } from '@/features/deposits/schemas'
import { labDetailOptions } from '@/features/labs/api/queries'
import { authenticatedRoute } from './authenticated'
import { prefetch, prefetchFor } from '@/lib/prefetch'

// Depositors, MTA templates and deposits of one lab, under the authenticated layout. The
// loaders prefetch with the components' own options and never throw: a lab the caller is not
// in (404) and a role that may not see these (403) are states of the page.

export const depositorListRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId/depositors',
  validateSearch: depositorListSearch,
  search: { middlewares: [stripSearchParams(depositorListDefaults)] },
  loaderDeps: ({ search }) => search,
  loader: ({ context, params, deps, cause }) =>
    Promise.all([
      prefetch(context.queryClient, labDetailOptions(params.labId)),
      prefetchFor(cause, context.queryClient, depositorListOptions(params.labId, deps)),
    ]),
  component: lazyRouteComponent(() => import('@/pages/DepositorListPage'), 'DepositorListPage'),
})

export const mtaListRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId/mta-templates',
  loader: ({ context, params }) =>
    Promise.all([prefetch(context.queryClient, labDetailOptions(params.labId)), prefetch(context.queryClient, mtaListOptions(params.labId))]),
  component: lazyRouteComponent(() => import('@/pages/MtaTemplateListPage'), 'MtaTemplateListPage'),
})

export const mtaNewRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId/mta-templates/new',
  validateSearch: mtaNewSearch,
  loaderDeps: ({ search }) => search,
  loader: ({ context, params, deps }) =>
    Promise.all([
      prefetch(context.queryClient, labDetailOptions(params.labId)),
      deps.from ? prefetch(context.queryClient, mtaDetailOptions(params.labId, deps.from)) : undefined,
    ]),
  component: lazyRouteComponent(() => import('@/pages/MtaTemplateNewPage'), 'MtaTemplateNewPage'),
})

export const mtaDetailRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId/mta-templates/$templateId',
  loader: ({ context, params }) =>
    Promise.all([
      prefetch(context.queryClient, labDetailOptions(params.labId)),
      prefetch(context.queryClient, mtaDetailOptions(params.labId, params.templateId)),
    ]),
  component: lazyRouteComponent(() => import('@/pages/MtaTemplateDetailPage'), 'MtaTemplateDetailPage'),
})

export const depositListRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId/deposits',
  validateSearch: depositListSearch,
  search: { middlewares: [stripSearchParams(depositListDefaults)] },
  loaderDeps: ({ search }) => search,
  loader: ({ context, params, deps, cause }) =>
    Promise.all([
      prefetch(context.queryClient, labDetailOptions(params.labId)),
      prefetchFor(cause, context.queryClient, depositListOptions(params.labId, deps)),
    ]),
  component: lazyRouteComponent(() => import('@/pages/DepositListPage'), 'DepositListPage'),
})

export const depositReceiveRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId/deposits/new',
  loader: ({ context, params }) =>
    Promise.all([prefetch(context.queryClient, labDetailOptions(params.labId)), prefetch(context.queryClient, mtaListOptions(params.labId))]),
  component: lazyRouteComponent(() => import('@/pages/DepositReceivePage'), 'DepositReceivePage'),
})

export const depositDetailRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId/deposits/$depositId',
  loader: ({ context, params }) =>
    Promise.all([
      prefetch(context.queryClient, labDetailOptions(params.labId)),
      prefetch(context.queryClient, depositDetailOptions(params.labId, params.depositId)),
    ]),
  component: lazyRouteComponent(() => import('@/pages/DepositDetailPage'), 'DepositDetailPage'),
})
