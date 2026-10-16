import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { api, ensureCsrf, unwrap } from '@/lib/api'
import type { LoginInput } from '../schemas'
import { authKeys } from './keys'

export function useLogin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: LoginInput) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/auth/login/', { body: input }))
    },
    // The form shows every failure itself: no global message.
    meta: { handlesError: true },
    onSuccess: (me) => {
      qc.clear() // nothing cached for an earlier user (or for the anonymous state) survives
      qc.setQueryData(authKeys.me(), me)
    },
  })
}

export function useLogout() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  return useMutation({
    mutationFn: async () => {
      await ensureCsrf()
      await unwrap(api.POST('/api/v1/auth/logout/'))
    },
    // Settled, not success: a failed logout must not leave the old user's data on screen.
    onSettled: async () => {
      qc.clear()
      await navigate({ to: '/login' })
    },
  })
}
