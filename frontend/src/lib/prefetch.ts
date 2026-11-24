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

/**
 * For a list that follows the page's search (#292): on entering the page the loader waits for it
 * as prefetch() does. When only the search changes on the same page (cause 'stay': the next page,
 * a filter), it starts the query and does not wait, so the router shows no pending screen after a
 * second, which took the page and the focused Next button with it on a slow server. The list keeps
 * its previous rows meanwhile (placeholderData: keepPreviousData) and says it is loading.
 */
export function prefetchFor<TQueryFnData, TError = DefaultError, TData = TQueryFnData, TQueryData = TQueryFnData, TQueryKey extends QueryKey = QueryKey>(
  cause: 'enter' | 'stay' | 'preload',
  client: QueryClient,
  options: QueryExecuteOptions<TQueryFnData, TError, TData, TQueryData, TQueryKey>,
): Promise<void> {
  const loading = prefetch(client, options)
  return cause === 'stay' ? Promise.resolve() : loading
}
