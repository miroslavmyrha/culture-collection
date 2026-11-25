import { createRoute, lazyRouteComponent } from '@tanstack/react-router'
import { labDetailOptions } from '@/features/labs/api/queries'
import { authenticatedRoute } from './authenticated'
import { prefetch } from '@/lib/prefetch'

// Importing a former catalogue (#70), under the authenticated layout. The loader never throws:
// a lab the caller is not in (404) and a role that may not import are states of the page.
export const catalogueImportRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'labs/$labId/catalogue-import',
  loader: ({ context, params }) => prefetch(context.queryClient, labDetailOptions(params.labId)),
  component: lazyRouteComponent(() => import('@/pages/CatalogueImportPage'), 'CatalogueImportPage'),
})
