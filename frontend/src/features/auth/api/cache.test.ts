import { MutationObserver, QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import { notify } from '@/lib/notify'
import { makeMe } from '@/test/factories'
import { resetSessionCache } from './cache'
import { authKeys } from './keys'

describe('resetSessionCache', () => {
  it('drops every query and mutation of the previous session and the notices, and keeps me with the new user', async () => {
    const client = new QueryClient()
    client.setQueryData(['labs', 'list'], ['secret'])
    client.setQueryData(authKeys.me(), makeMe({ username: 'before' }))
    await client.getMutationCache().build(client, { mutationFn: () => Promise.resolve('done') }).execute(undefined)
    notify.error('Something from before.')
    const meQuery = client.getQueryCache().find({ queryKey: authKeys.me() })

    resetSessionCache(client, makeMe({ username: 'after' }))

    expect(client.getQueryData(['labs', 'list'])).toBeUndefined()
    expect(client.getQueryData(authKeys.me())).toMatchObject({ username: 'after' })
    // The same query object: an observer that stays mounted keeps reading it.
    expect(client.getQueryCache().find({ queryKey: authKeys.me() })).toBe(meQuery)
    expect(client.getMutationCache().getAll()).toEqual([])
    expect(notify.get()).toEqual([])
  })

  // MutationCache.clear() only forgets the mutations (query-core 5.104.3,
  // build/modern/mutationCache.js:126-137). A request still running is not cancelled: it ends
  // as it would have, its observer (the component that started it) still gets the result
  // (mutation.js:283-285), and it does not come back into the cache.
  it('lets a mutation that is still running finish for its observer, outside the cache', async () => {
    const client = new QueryClient()
    const gate: { open?: (value: string) => void } = {}
    const answer = new Promise<string>((resolve) => {
      gate.open = resolve
    })
    const observer = new MutationObserver(client, { mutationFn: () => answer })
    const seen: string[] = []
    const unsubscribe = observer.subscribe((result) => seen.push(result.status))
    const running = observer.mutate()
    expect(client.getMutationCache().getAll()).toHaveLength(1)

    resetSessionCache(client, null)
    expect(client.getMutationCache().getAll()).toEqual([])

    gate.open?.('answer')
    await expect(running).resolves.toBe('answer')
    expect(observer.getCurrentResult()).toMatchObject({ status: 'success', data: 'answer' })
    expect(seen).toEqual(['pending', 'success'])
    expect(client.getMutationCache().getAll()).toEqual([])
    unsubscribe()
  })
})
