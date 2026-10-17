import { createRouter, type RouterHistory } from '@tanstack/react-router'
import type { QueryClient } from '@tanstack/react-query'
import { NotFound, Pending, RouteError } from '@/components/RouteStates'
import { isApiError } from '@/lib/api'
import { reportError } from '@/lib/report'
import { authenticatedRoute } from '@/routes/authenticated'
import { homeRoute } from '@/routes/home'
import { labDetailRoute, labListRoute } from '@/routes/labs'
import { loginRoute } from '@/routes/login'
import { rootRoute } from '@/routes/root'

export const routeTree = rootRoute.addChildren([loginRoute, authenticatedRoute.addChildren([homeRoute, labListRoute, labDetailRoute])])

export function createAppRouter(queryClient: QueryClient, history?: RouterHistory) {
  return createRouter({
    routeTree,
    history,
    context: { queryClient },
    // Preload on hover or focus; the query cache decides freshness, not the router.
    defaultPreload: 'intent',
    defaultPreloadStaleTime: 0,
    defaultErrorComponent: RouteError,
    defaultNotFoundComponent: NotFound,
    defaultPendingComponent: Pending,
    // API errors were already reported by the query cache; report only the rest (render bugs).
    defaultOnCatch: (error) => {
      if (!isApiError(error)) reportError(error, { source: 'route' })
    },
  })
}

export type AppRouter = ReturnType<typeof createAppRouter>

declare module '@tanstack/react-router' {
  interface Register {
    router: AppRouter
  }
}
