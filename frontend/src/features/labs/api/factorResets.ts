import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { components } from '@/api/schema'
import { api, unwrap } from '@/lib/api'
import { labKeys } from './keys'

export type FactorReset = components['schemas']['FactorResetOutput']

const resetKeys = (labId: string) => [...labKeys.all, 'factor-resets', labId] as const

/** The open second factor resets of a lab, for its managers (#176). */
export function useFactorResets(labId: string) {
  return useQuery({
    queryKey: resetKeys(labId),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/auth/factor-resets/', { signal, params: { query: { lab: labId } } })),
  })
}

export function useProposeReset(labId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: components['schemas']['FactorResetInputRequest']) => unwrap(api.POST('/api/v1/auth/factor-resets/propose/', { body })),
    meta: { handlesError: true },
    onSuccess: () => qc.invalidateQueries({ queryKey: resetKeys(labId) }),
  })
}

export function useDecideReset(labId: string, decision: 'confirm' | 'withdraw') {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ publicId, reason }: { publicId: string; reason: string }) => {
      const params = { path: { public_id: publicId } }
      return unwrap(
        decision === 'confirm'
          ? api.POST('/api/v1/auth/factor-resets/{public_id}/confirm/', { params, body: { reason } })
          : api.POST('/api/v1/auth/factor-resets/{public_id}/withdraw/', { params, body: { reason } }),
      )
    },
    meta: { handlesError: true },
    onSuccess: () => qc.invalidateQueries({ queryKey: resetKeys(labId) }),
  })
}

/** A one-time code for a member's first enrolment of a second factor (#176), shown once. */
export function useIssueEnrolmentCode() {
  return useMutation({
    mutationFn: (body: components['schemas']['EnrolmentCodeIssueInputRequest']) => unwrap(api.POST('/api/v1/auth/enrolment-codes/', { body })),
    meta: { handlesError: true },
  })
}
