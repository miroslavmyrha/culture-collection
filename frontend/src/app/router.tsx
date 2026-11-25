import { createRouter, type RouterHistory } from '@tanstack/react-router'
import type { QueryClient } from '@tanstack/react-query'
import { NotFound, Pending, RouteError } from '@/components/RouteStates'
import { useMe } from '@/features/auth/api/queries'
import { isApiError } from '@/lib/api'
import { reportError } from '@/lib/report'
import { authenticatedRoute } from '@/routes/authenticated'
import { catalogueImportRoute } from '@/routes/catalogue'
import { classificationRoute } from '@/routes/classification'
import { depositDetailRoute, depositListRoute, depositorListRoute, depositReceiveRoute, mtaDetailRoute, mtaListRoute, mtaNewRoute } from '@/routes/deposits'
import { requestDetailRoute, requesterListRoute, requestListRoute, requestNewRoute, shipmentDocumentRoute } from '@/routes/distribution'
import { homeRoute } from '@/routes/home'
import { labDetailRoute, labListRoute, vratAccessRoute } from '@/routes/labs'
import { loginRoute } from '@/routes/login'
import { mediaListRoute } from '@/routes/media'
import { permitListRoute } from '@/routes/permits'
import { revealListRoute } from '@/routes/reveals'
import { securityRoute } from '@/routes/account'
import { rootRoute } from '@/routes/root'
import { storageRoute, storageUnitRoute } from '@/routes/storage'
import { strainDetailRoute, strainHistoryRoute, strainListRoute, strainMaterialRoute, strainOverviewRoute, strainTermsRoute } from '@/routes/strains'

export const routeTree = rootRoute.addChildren([
  loginRoute,
  authenticatedRoute.addChildren([homeRoute, labListRoute, labDetailRoute, strainListRoute, strainDetailRoute.addChildren([strainOverviewRoute, strainMaterialRoute, strainTermsRoute, strainHistoryRoute]), depositorListRoute, mtaListRoute, mtaNewRoute, mtaDetailRoute, depositListRoute, depositReceiveRoute, depositDetailRoute, storageRoute, storageUnitRoute, requestListRoute, requestNewRoute, requestDetailRoute, requesterListRoute, shipmentDocumentRoute, permitListRoute, mediaListRoute, revealListRoute, vratAccessRoute, classificationRoute, catalogueImportRoute, securityRoute]),
])

/**
 * An unknown address runs no route that loads the session, and the shell only reads the cache:
 * the not-found page asks for it, so a signed-in user who opened the address directly keeps the
 * top bar (#227).
 */
function AppNotFound() {
  useMe()
  return <NotFound />
}

export function createAppRouter(queryClient: QueryClient, history?: RouterHistory) {
  return createRouter({
    routeTree,
    history,
    context: { queryClient },
    // Preload on hover or focus; the query cache decides freshness, not the router.
    defaultPreload: 'intent',
    defaultPreloadStaleTime: 0,
    defaultErrorComponent: RouteError,
    defaultNotFoundComponent: AppNotFound,
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
