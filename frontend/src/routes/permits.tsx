import { createRoute, lazyRouteComponent } from '@tanstack/react-router'
import { labDetailOptions } from '@/features/labs/api/queries'
import { permitListOptions } from '@/features/permits/api/queries'
import { authenticatedRoute } from './authenticated'
import { prefetch } from '@/lib/prefetch'

// The lab's permits (#82), under the authenticated layout. The loader prefetches with the
// components' own options and never throws: a lab the caller is not in (404) and a role that
// may not see the permits (403) are states of the page.
export const permitListRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId/permits',
  loader: ({ context, params }) =>
    Promise.all([prefetch(context.queryClient, labDetailOptions(params.labId)), prefetch(context.queryClient, permitListOptions(params.labId))]),
  component: lazyRouteComponent(() => import('@/pages/PermitListPage'), 'PermitListPage'),
})
