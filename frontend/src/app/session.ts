import type { QueryClient } from '@tanstack/react-query'
import type { AnyRouter } from '@tanstack/react-router'
import { resetSessionCache } from '@/features/auth/api/cache'
import { safeRedirect } from '@/lib/safe'

/**
 * The one 401 handler. Parallel 401s cause one redirect; nothing happens on the login page.
 * The session in the cache ends first (the previous user's data dropped, me set to null), so
 * the login route's guard and the shell see the anonymous state the server just reported.
 */
export function createUnauthorizedHandler(getRouter: () => AnyRouter, queryClient: QueryClient) {
  let redirecting = false
  return () => {
    const router = getRouter()
    const { pathname, href } = router.state.location
    if (redirecting || pathname === '/login') return
    redirecting = true
    resetSessionCache(queryClient, null)
    void router
      .navigate({ to: '/login', search: { redirect: safeRedirect(href) }, replace: true })
      .finally(() => {
        redirecting = false
      })
  }
}
