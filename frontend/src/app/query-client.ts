import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'
import { errorMessage, isApiError, retryDelay, shouldRetry } from '@/lib/api'
import { notify } from '@/lib/notify'
import { reportError } from '@/lib/report'

declare module '@tanstack/react-query' {
  interface Register {
    /**
     * handlesError: the caller shows the failure itself, so the global message stays quiet.
     * errorMessage: the global message for this mutation instead of the generic one by status.
     */
    mutationMeta: { handlesError?: boolean; errorMessage?: string }
  }
}

type Options = {
  /** Called on every 401 (session expired). The app redirects to the login page once. */
  onUnauthorized?: () => void
}

/** Report only what is unexpected: 4xx are answers, not bugs. */
function reportUnexpected(error: unknown, source: string) {
  if (isApiError(error) && error.status > 0 && error.status < 500) return
  reportError(error, isApiError(error) && error.requestId ? { source, requestId: error.requestId } : { source })
}

export function makeQueryClient({ onUnauthorized }: Options = {}) {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (error) => {
        if (isApiError(error, 401)) return onUnauthorized?.()
        reportUnexpected(error, 'query')
      },
    }),
    mutationCache: new MutationCache({
      onError: (error, _variables, _result, mutation) => {
        if (isApiError(error, 401)) return onUnauthorized?.()
        reportUnexpected(error, 'mutation')
        if (!mutation.meta?.handlesError) notify.error(mutation.meta?.errorMessage ?? errorMessage(error))
      },
    }),
    defaultOptions: {
      queries: { retry: shouldRetry, retryDelay, staleTime: 30_000 },
      mutations: { retry: false }, // never retry writes blindly
    },
  })
}
