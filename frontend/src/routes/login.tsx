import { createRoute, lazyRouteComponent, redirect } from '@tanstack/react-router'
import { z } from 'zod'
import { meQueryOptions } from '@/features/auth/api/queries'
import { safeRedirect } from '@/lib/safe'
import { rootRoute } from './root'

// .catch: a bad or hostile value falls back instead of failing the route.
export const loginSearchSchema = z.object({ redirect: z.string().optional().catch(undefined) })

export const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: 'login',
  validateSearch: loginSearchSchema,
  beforeLoad: async ({ context, search }) => {
    const me = await context.queryClient.ensureQueryData(meQueryOptions())
    if (me) throw redirect({ href: safeRedirect(search.redirect) })
  },
  component: lazyRouteComponent(() => import('@/pages/LoginPage'), 'LoginPage'),
})
