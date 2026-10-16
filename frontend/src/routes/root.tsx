import type { QueryClient } from '@tanstack/react-query'
import { createRootRouteWithContext, Outlet } from '@tanstack/react-router'

export type RouterContext = { queryClient: QueryClient }

export const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: Outlet,
})
