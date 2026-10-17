import type { QueryClient } from '@tanstack/react-query'
import { createRootRouteWithContext, Outlet } from '@tanstack/react-router'
import { Layout } from '@/app/Layout'

export type RouterContext = { queryClient: QueryClient }

export const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: RootLayout,
})

function RootLayout() {
  return (
    <Layout>
      <Outlet />
    </Layout>
  )
}
