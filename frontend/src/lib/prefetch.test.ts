import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import { prefetch, prefetchFor } from './prefetch'

describe('prefetch', () => {
  it('puts the answer in the cache', async () => {
    const client = new QueryClient()
    await prefetch(client, { queryKey: ['p', 1], queryFn: () => Promise.resolve('answer') })
    expect(client.getQueryData(['p', 1])).toBe('answer')
  })

  it('resolves when the query fails, and leaves the failure in the cache for the page', async () => {
    const client = new QueryClient()
    await expect(prefetch(client, { queryKey: ['p', 2], queryFn: () => Promise.reject(new Error('down')) })).resolves.toBeUndefined()
    expect(client.getQueryState(['p', 2])?.status).toBe('error')
  })
})

// A loader waits for a search-dependent list on entering its page, not when only the search
// changes (#292): the router then keeps the page instead of a pending screen.
const slow = (key: string, settle: { done: boolean }) => ({
  queryKey: [key],
  queryFn: () =>
    new Promise<string>((resolve) =>
      setTimeout(() => {
        settle.done = true
        resolve('rows')
      }, 30),
    ),
})

describe('prefetchFor', () => {
  it.each(['enter', 'preload'] as const)('waits for the list on %s', async (cause) => {
    const settle = { done: false }
    await prefetchFor(cause, new QueryClient(), slow(cause, settle))
    expect(settle.done).toBe(true)
  })

  it('starts the list but does not wait when only the search changed', async () => {
    const client = new QueryClient()
    const settle = { done: false }
    await prefetchFor('stay', client, slow('stay', settle))
    expect(settle.done).toBe(false)
    await expect.poll(() => client.getQueryData(['stay'])).toBe('rows')
  })
})
