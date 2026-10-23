import { createRoute, lazyRouteComponent } from '@tanstack/react-router'
import { activityOptions, overviewOptions } from '@/features/home/api/queries'
import { authenticatedRoute } from './authenticated'

export const homeRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: '/',
  // Fresh on every arrival: what waits changes with every write in every lab. The loader never
  // throws: a failed read is a state of the page.
  loader: ({ context }) =>
    Promise.all([
      context.queryClient.prefetchQuery({ ...overviewOptions(), staleTime: 0 }),
      context.queryClient.prefetchQuery({ ...activityOptions(), staleTime: 0 }),
    ]),
  component: lazyRouteComponent(() => import('@/pages/HomePage'), 'HomePage'),
})
