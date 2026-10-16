import type { QueryClient } from '@tanstack/react-query'
import type { AnyRouter } from '@tanstack/react-router'
import { safeRedirect } from '@/lib/safe'

/**
 * The one 401 handler. Parallel 401s cause one redirect; nothing happens on the login page.
 * The cache is emptied first, so the login route's guard asks the server again instead of
 * trusting the cached user.
 */
export function createUnauthorizedHandler(getRouter: () => AnyRouter, queryClient: QueryClient) {
  let redirecting = false
  return () => {
    const router = getRouter()
    const { pathname, href } = router.state.location
    if (redirecting || pathname === '/login') return
    redirecting = true
    queryClient.clear()
    void router
      .navigate({ to: '/login', search: { redirect: safeRedirect(href) }, replace: true })
      .finally(() => {
        redirecting = false
      })
  }
}
