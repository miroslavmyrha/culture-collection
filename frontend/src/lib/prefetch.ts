import type { DefaultError, QueryClient, QueryExecuteOptions, QueryKey } from '@tanstack/react-query'

/**
 * Load a query into the cache for a page about to show it (#226). A failure is left to the page,
 * which reads the same query and shows its error with a retry, so a route loader that awaits
 * several of these never fails on one. This is what the deprecated `prefetchQuery` did.
 */
export function prefetch<TQueryFnData, TError = DefaultError, TData = TQueryFnData, TQueryData = TQueryFnData, TQueryKey extends QueryKey = QueryKey>(
  client: QueryClient,
  options: QueryExecuteOptions<TQueryFnData, TError, TData, TQueryData, TQueryKey>,
): Promise<void> {
  return client.query(options).then(
    () => undefined,
    () => undefined,
  )
}
