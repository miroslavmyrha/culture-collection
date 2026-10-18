import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { meQueryOptions } from '@/features/auth/api/queries'
import { api, ensureCsrf, unwrap } from '@/lib/api'
import { makeMe } from './factories'
import { holdApi, mockApi, recordRequests } from './mockApi'

describe('mockApi', () => {
  it('is typed by the generated schema', () => {
    // @ts-expect-error the body must match MeOutput
    mockApi('get', '/api/v1/auth/me/', { name: 'wrong shape' })
    // @ts-expect-error the path must exist for the method
    mockApi('delete', '/api/v1/auth/me/', undefined)
    // @ts-expect-error the cache entry is typed by the query options too
    new QueryClient().setQueryData(meQueryOptions().queryKey, { name: 'wrong shape' })
    expect(true).toBe(true)
  })

  it('returns the requests it answered', async () => {
    const calls = mockApi('post', '/api/v1/auth/login/', makeMe(), { status: 200 })
    await ensureCsrf()
    await unwrap(api.POST('/api/v1/auth/login/', { body: { username: 'a', password: 'b' } }))
    expect(calls).toHaveLength(1)
    expect(calls[0]).toMatchObject({ method: 'POST', body: { username: 'a', password: 'b' } })
    expect(calls[0]?.url.pathname).toBe('/api/v1/auth/login/')
  })

  it('recordRequests observes and lets the next handler answer', async () => {
    const me = makeMe()
    mockApi('get', '/api/v1/auth/me/', me)
    const calls = recordRequests('get', '/api/v1/auth/me/')
    await expect(unwrap(api.GET('/api/v1/auth/me/'))).resolves.toEqual(me)
    expect(calls).toHaveLength(1)
  })

  it('holdApi answers nothing until release, then the held request and every later one', async () => {
    const held = holdApi('post', '/api/v1/auth/logout/')
    let settled = false
    const first = unwrap(api.POST('/api/v1/auth/logout/')).finally(() => {
      settled = true
    })
    await vi.waitFor(() => expect(held.calls).toHaveLength(1))
    expect(settled).toBe(false)
    held.release(500, { status: 500 })
    await expect(first).rejects.toMatchObject({ status: 500 })
    await expect(unwrap(api.POST('/api/v1/auth/logout/'))).rejects.toMatchObject({ status: 500 })
    expect(held.calls).toHaveLength(2)
  })
})
