import type { QueryClient } from '@tanstack/react-query'
import type { components } from '@/api/schema'
import { notify } from '@/lib/notify'
import { authKeys } from './keys'

type Me = components['schemas']['MeOutput']

const ME_KEY = JSON.stringify(authKeys.me())

/**
 * Starts a new session in the cache: login, logout and every 401 go through here.
 * Every query of the previous user is dropped. The me query itself stays and gets the new user
 * (or null): queryClient.clear() would destroy it, and an observer that stays mounted across
 * the change (the shell's top bar) would keep showing the previous user.
 * Mutations go too, or the previous user's variables (a username typed into a form) stay in
 * the mutation cache. clear() does not cancel one still running: it finishes for the component
 * that started it, outside the cache (cache.test.ts).
 * Global notices go too: they speak about the previous session ("Sign-out failed. You are still
 * signed in." must not stay on the login page after a retry succeeded).
 */
export function resetSessionCache(queryClient: QueryClient, me: Me | null): void {
  queryClient.removeQueries({ predicate: (query) => JSON.stringify(query.queryKey) !== ME_KEY })
  queryClient.setQueryData(authKeys.me(), me)
  queryClient.getMutationCache().clear()
  notify.clear()
}
