import type { RouterHistory } from '@tanstack/react-router'
import { makeQueryClient } from './query-client'
import { type AppRouter, createAppRouter } from './router'
import { createUnauthorizedHandler } from './session'

/** One QueryClient and one router that share it through the router context. */
export function createApp({ history }: { history?: RouterHistory } = {}) {
  let router: AppRouter | undefined
  const queryClient = makeQueryClient({
    onUnauthorized: () => onUnauthorized(),
  })
  const onUnauthorized = createUnauthorizedHandler(() => {
    if (!router) throw new Error('router not created yet')
    return router
  }, queryClient)
  router = createAppRouter(queryClient, history)
  return { queryClient, router }
}
