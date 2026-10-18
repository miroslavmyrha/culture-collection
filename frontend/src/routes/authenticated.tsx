import { createRoute, redirect } from '@tanstack/react-router'
import { meQueryOptions } from '@/features/auth/api/queries'
import { safeRedirect } from '@/lib/safe'
import { rootRoute } from './root'

/**
 * Pathless layout: every route below it needs a session. The guard runs before any child
 * loads, so a protected page never mounts, flashes or fires its queries for anonymous users.
 */
export const authenticatedRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: '_authenticated',
  beforeLoad: async ({ context, location }) => {
    const me = await context.queryClient.ensureQueryData(meQueryOptions())
    // The router's own location, so already a same-origin path; the helper keeps every redirect
    // target on one rule (tools/redirect-sinks.test.ts).
    if (!me) throw redirect({ to: '/login', search: { redirect: safeRedirect(location.href) } })
    return { me }
  },
})
