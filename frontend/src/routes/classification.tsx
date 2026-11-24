import { createRoute, lazyRouteComponent, stripSearchParams } from '@tanstack/react-router'
import { labDetailOptions } from '@/features/labs/api/queries'
import { strainDisagreementsOptions } from '@/features/strains/api/queries'
import { pageDefaults, pageSearch } from '@/lib/paging'
import { authenticatedRoute } from './authenticated'
import { prefetch, prefetchFor } from '@/lib/prefetch'

// Where the lab's classification disagrees with the official lists (#169), under the
// authenticated layout. The loader prefetches with the component's own options and never
// throws: a lab the caller is not in (404) and a role that may not see the check (403) are
// states of the page.
export const classificationRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId/classification',
  validateSearch: pageSearch,
  search: { middlewares: [stripSearchParams(pageDefaults)] },
  loaderDeps: ({ search }) => search,
  loader: ({ context, params, deps, cause }) =>
    Promise.all([prefetch(context.queryClient, labDetailOptions(params.labId)), prefetchFor(cause, context.queryClient, strainDisagreementsOptions(params.labId, deps))]),
  component: lazyRouteComponent(() => import('@/pages/ClassificationPage'), 'ClassificationPage'),
})
