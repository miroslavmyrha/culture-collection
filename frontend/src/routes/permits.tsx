import { createRoute, lazyRouteComponent } from '@tanstack/react-router'
import { labDetailOptions } from '@/features/labs/api/queries'
import { permitListOptions } from '@/features/permits/api/queries'
import { authenticatedRoute } from './authenticated'

// The lab's permits (#82), under the authenticated layout. The loader prefetches with the
// components' own options and never throws: a lab the caller is not in (404) and a role that
// may not see the permits (403) are states of the page.
export const permitListRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId/permits',
  loader: ({ context, params }) =>
    Promise.all([context.queryClient.prefetchQuery(labDetailOptions(params.labId)), context.queryClient.prefetchQuery(permitListOptions(params.labId))]),
  component: lazyRouteComponent(() => import('@/pages/PermitListPage'), 'PermitListPage'),
})
