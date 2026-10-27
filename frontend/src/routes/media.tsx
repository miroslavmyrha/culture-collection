import { createRoute, lazyRouteComponent } from '@tanstack/react-router'
import { labDetailOptions } from '@/features/labs/api/queries'
import { mediaListOptions } from '@/lib/growth'
import { authenticatedRoute } from './authenticated'

// The lab's media (#79), under the authenticated layout. The loader prefetches with the
// components' own options and never throws: a lab the caller is not in (404) is a state of the page.
export const mediaListRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId/media',
  loader: ({ context, params }) =>
    Promise.all([context.queryClient.prefetchQuery(labDetailOptions(params.labId)), context.queryClient.prefetchQuery(mediaListOptions(params.labId))]),
  component: lazyRouteComponent(() => import('@/pages/MediaListPage'), 'MediaListPage'),
})
