import { createRoute, lazyRouteComponent } from '@tanstack/react-router'
import { authenticatedRoute } from './authenticated'

// The signed-in user's second factors (#176), under the authenticated layout.
export const securityRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: 'account/security',
  component: lazyRouteComponent(() => import('@/pages/SecurityPage'), 'SecurityPage'),
})
