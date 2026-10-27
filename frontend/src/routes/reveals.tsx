import { createRoute, lazyRouteComponent, stripSearchParams } from '@tanstack/react-router'
import { labDetailOptions } from '@/features/labs/api/queries'
import { revealListOptions } from '@/features/reveals/api/queries'
import { revealListDefaults, revealListSearch } from '@/features/reveals/schemas'
import { authenticatedRoute } from './authenticated'

// The lab's reveal log (#83), under the authenticated layout. The loader prefetches with the
// components' own options and never throws: a lab the caller is not in (404) and a role that
// may not see the log (403) are states of the page.
export const revealListRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId/reveals',
  validateSearch: revealListSearch,
  search: { middlewares: [stripSearchParams(revealListDefaults)] },
  loaderDeps: ({ search }) => search,
  loader: ({ context, params, deps }) =>
    Promise.all([context.queryClient.prefetchQuery(labDetailOptions(params.labId)), context.queryClient.prefetchQuery(revealListOptions(params.labId, deps))]),
  component: lazyRouteComponent(() => import('@/pages/RevealListPage'), 'RevealListPage'),
})
