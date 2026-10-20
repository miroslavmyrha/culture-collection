import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query'
import type { components } from '@/api/schema'
import { api, ensureCsrf, unwrap } from '@/lib/api'
import { sharedKeys } from '@/lib/shared-keys'
import { depositKeys, depositorKeys, mtaKeys } from './keys'

type Schemas = components['schemas']
type Deposit = Schemas['DepositDetailOutput']

// Each form and dialog shows its own failure (meta.handlesError). A write answers with the
// detail it changed: it goes into the cache, the lab's lists are invalidated, and the returned
// promise keeps the mutation pending until they are fresh.
function settleDeposit(qc: QueryClient, labId: string, deposit: Deposit) {
  qc.setQueryData(depositKeys.detail(labId, deposit.public_id), deposit)
  return qc.invalidateQueries({ queryKey: depositKeys.lists(labId) })
}

const lab = (labId: string) => ({ params: { path: { lab_public_id: labId } } })
const one = (labId: string, id: string) => ({ params: { path: { lab_public_id: labId, public_id: id } } })

export function useCreateDepositor(labId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['DepositorInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/depositors/', { ...lab(labId), body }))
    },
    meta: { handlesError: true },
    onSuccess: () => qc.invalidateQueries({ queryKey: depositorKeys.lists(labId) }),
  })
}

export function useUpdateDepositor(labId: string, depositorId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['DepositorInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.PUT('/api/v1/labs/{lab_public_id}/depositors/{public_id}/', { ...one(labId, depositorId), body }))
    },
    meta: { handlesError: true },
    // A deposit shows its depositor's name: those change too.
    onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: depositorKeys.lists(labId) }), qc.invalidateQueries({ queryKey: depositKeys.lab(labId) })]),
  })
}

export function usePublishMta(labId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['MtaTemplateInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/mta-templates/', { ...lab(labId), body }))
    },
    meta: { handlesError: true },
    onSuccess: (template) => {
      qc.setQueryData(mtaKeys.detail(labId, template.public_id), template)
      return qc.invalidateQueries({ queryKey: mtaKeys.lists(labId) })
    },
  })
}

export function useReceiveDeposit(labId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['DepositReceiveInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/deposits/', { ...lab(labId), body }))
    },
    meta: { handlesError: true },
    onSuccess: (deposit) => settleDeposit(qc, labId, deposit),
  })
}

export function useReplaceTerms(labId: string, depositId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['TermsReplaceInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/deposits/{public_id}/terms/', { ...one(labId, depositId), body }))
    },
    meta: { handlesError: true },
    onSuccess: (deposit) => settleDeposit(qc, labId, deposit),
  })
}

export function useStartCheck(labId: string, depositId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/deposits/{public_id}/start-check/', one(labId, depositId)))
    },
    meta: { handlesError: true },
    onSuccess: (deposit) => settleDeposit(qc, labId, deposit),
  })
}

/** Acceptance creates the strain: the lab's strain lists are invalidated too (shared keys). */
export function useAcceptDeposit(labId: string, depositId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['StrainFactsInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/deposits/{public_id}/accept/', { ...one(labId, depositId), body }))
    },
    meta: { handlesError: true },
    onSuccess: (deposit) => Promise.all([settleDeposit(qc, labId, deposit), qc.invalidateQueries({ queryKey: sharedKeys.strainLists(labId) })]),
  })
}

export function useRejectDeposit(labId: string, depositId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['RejectInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/deposits/{public_id}/reject/', { ...one(labId, depositId), body }))
    },
    meta: { handlesError: true },
    onSuccess: (deposit) => settleDeposit(qc, labId, deposit),
  })
}
