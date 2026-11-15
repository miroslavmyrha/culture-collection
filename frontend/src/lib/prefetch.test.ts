import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import { prefetch } from './prefetch'

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
