import { createRoute, lazyRouteComponent } from '@tanstack/react-router'
import { authenticatedRoute } from './authenticated'

export const homeRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: '/',
  component: lazyRouteComponent(() => import('@/pages/HomePage'), 'HomePage'),
})
