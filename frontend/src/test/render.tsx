import type { QueryClient } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRouteWithContext,
  createRoute,
  createRouter,
  defaultStringifySearch,
  Outlet,
  RouterProvider,
} from '@tanstack/react-router'
import { render, renderHook } from '@testing-library/react'
import { createContext, type ReactElement, type ReactNode, use } from 'react'
import { createApp } from '@/app/create-app'
import { makeQueryClient } from '@/app/query-client'
import { Providers } from '@/app/providers'
import type { RouterContext } from '@/routes/root'

type Options = {
  /** Current URL path, e.g. '/samples'. */
  path?: string
  /** Search params, serialised the way the router does it. */
  search?: Record<string, unknown>
  client?: QueryClient
}

/** The app's QueryClient defaults (status-aware retry off, so failures show at once). */
export function makeTestQueryClient(): QueryClient {
  const client = makeQueryClient()
  const defaults = client.getDefaultOptions()
  client.setDefaultOptions({ ...defaults, queries: { ...defaults.queries, retry: false } })
  return client
}

const url = (path: string, search?: Record<string, unknown>) => path + (search ? defaultStringifySearch(search) : '')

const Ui = createContext<ReactNode>(null)
function RenderUi() {
  return use(Ui)
}

async function setup({ path = '/', search, client = makeTestQueryClient() }: Options) {
  const root = createRootRouteWithContext<RouterContext>()({ component: Outlet })
  const index = createRoute({ getParentRoute: () => root, path: '/', component: RenderUi })
  const any = createRoute({ getParentRoute: () => root, path: '$', component: RenderUi })
  const router = createRouter({
    routeTree: root.addChildren([index, any]),
    history: createMemoryHistory({ initialEntries: [url(path, search)] }),
    context: { queryClient: client },
  })
  // Resolve the first route before rendering, so the first render already shows `ui`.
  await router.load()
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <Providers client={client}>
        <Ui value={children}>
          <RouterProvider router={router} />
        </Ui>
      </Providers>
    )
  }
  return { client, router, Wrapper }
}

/**
 * Renders `ui` inside the app providers and a memory-history router at {path, search}.
 * Providers go through the `wrapper` option, so rerender() keeps them. Async because the
 * router resolves its first match before rendering: always await it (lint flags a floating
 * promise). Assert URLs on router.state.location.
 */
export async function renderWithProviders(ui: ReactElement, options: Options = {}) {
  const { client, router, Wrapper } = await setup(options)
  return { client, router, ...render(ui, { wrapper: Wrapper }) }
}

/** Same providers and router for a reusable hook. Test other hooks through their component. */
export async function renderHookWithProviders<T>(hook: () => T, options: Options = {}) {
  const { client, router, Wrapper } = await setup(options)
  return { client, router, ...renderHook(hook, { wrapper: Wrapper }) }
}

/**
 * The whole app (real routes, guards, 401 handling) at a URL. Not pre-loaded: guards fetch,
 * so wait for the result with findBy* or waitFor.
 */
export function renderApp({ path = '/', search }: Omit<Options, 'client'> = {}) {
  const { queryClient, router } = createApp({ history: createMemoryHistory({ initialEntries: [url(path, search)] }) })
  const defaults = queryClient.getDefaultOptions()
  queryClient.setDefaultOptions({ ...defaults, queries: { ...defaults.queries, retry: false } })
  return {
    client: queryClient,
    router,
    ...render(
      <Providers client={queryClient}>
        <RouterProvider router={router} />
      </Providers>,
    ),
  }
}
