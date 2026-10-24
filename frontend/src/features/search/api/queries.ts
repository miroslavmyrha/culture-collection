import { keepPreviousData, queryOptions, useQuery } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'

export const searchKeys = {
  all: ['search'] as const,
  /** One key per folded text: "BAC 2" and "BAC  2" are one request. */
  text: (text: string) => [...searchKeys.all, text] as const,
}

/** One options object for the hook and for Enter, which may ask before the debounce did. */
export const searchOptions = (text: string) =>
  queryOptions({
    queryKey: searchKeys.text(text),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/me/search/', { signal, params: { query: { q: text } } })),
    // Typing on keeps the last results on screen until the next ones are in.
    placeholderData: keepPreviousData,
    // A result is read once and left; another search asks again.
    staleTime: 10_000,
    gcTime: 60_000,
  })

export function useSearch(text: string, enabled: boolean) {
  return useQuery({ ...searchOptions(text), enabled })
}
