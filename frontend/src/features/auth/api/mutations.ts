import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { api, ensureCsrf, isApiError, unwrap } from '@/lib/api'
import type { LoginInput } from '../schemas'
import { resetSessionCache } from './cache'

export function useLogin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: LoginInput) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/auth/login/', { body: input }))
    },
    // The form shows every failure itself: no global message.
    meta: { handlesError: true },
    // Nothing cached for an earlier user (or for the anonymous state) survives.
    onSuccess: (me) => resetSessionCache(qc, me),
  })
}

export const SIGN_OUT_FAILED = 'Sign-out failed. You are still signed in. Try again.'

export function useLogout() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  return useMutation({
    mutationFn: async () => {
      try {
        await ensureCsrf()
        await unwrap(api.POST('/api/v1/auth/logout/'))
      } catch (error) {
        // 401: the server has no session for us any more, which is what signing out wants.
        if (!isApiError(error, 401)) throw error
      }
    },
    // Only a confirmed end clears the cache and leaves the page. After a 5xx, a network error or
    // a CSRF 403 the session cookie still works: a sign-in form would then be shown to someone
    // who is still signed in, and on a shared PC the next person reloads into their session.
    // So the data and the page stay, and the global notice says what happened.
    meta: { errorMessage: SIGN_OUT_FAILED },
    onSuccess: async () => {
      resetSessionCache(qc, null)
      await navigate({ to: '/login', search: { signedOut: true } })
    },
  })
}
