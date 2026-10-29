import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query'
import type { components } from '@/api/schema'
import { api, ensureCsrf, unwrap } from '@/lib/api'
import { sharedKeys } from '@/lib/shared-keys'
import { requesterKeys, requestKeys } from './keys'

type Schemas = components['schemas']
type Request = Schemas['RequestDetailOutput']
type PermitBody = Omit<Schemas['PermitInputRequest'], 'file'>
type AcceptanceBody = Omit<Schemas['AcceptanceInputRequest'], 'file'>

const lab = (labId: string) => ({ params: { path: { lab_public_id: labId } } })
const one = (labId: string, id: string) => ({ params: { path: { lab_public_id: labId, public_id: id } } })

/** The fields as text and the file itself: what a multipart/form-data request carries. */
export function formData(fields: Record<string, string | number | boolean | null | undefined>, file: File): FormData {
  const data = new FormData()
  for (const [name, value] of Object.entries(fields)) if (value !== null && value !== undefined) data.append(name, String(value))
  data.append('file', file)
  return data
}

// Each form and dialog shows its own failure (meta.handlesError). A write answers with the
// detail it changed: it goes into the cache, the lab's lists are invalidated, and the returned
// promise keeps the mutation pending until they are fresh.
function settleRequest(qc: QueryClient, labId: string, request: Request) {
  qc.setQueryData(requestKeys.detail(labId, request.public_id), request)
  // What waits on Home and the Requests tab's count change with every move of a request.
  return Promise.all([qc.invalidateQueries({ queryKey: requestKeys.lists(labId) }), qc.invalidateQueries({ queryKey: sharedKeys.overview() })])
}

/**
 * Approving, cancelling, shipping and confirming a prepared shipment change vials (reserved, available again, distributed and
 * out of their boxes, a batch exhausted): the strain pages and box grids show them, so the
 * material of the lab is invalidated too (lib/shared-keys).
 */
function settleVials(qc: QueryClient, labId: string, request: Request) {
  return Promise.all([settleRequest(qc, labId, request), qc.invalidateQueries({ queryKey: sharedKeys.material(labId) })])
}

export function useSubmitRequest(labId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['RequestInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/requests/', { ...lab(labId), body }))
    },
    meta: { handlesError: true },
    onSuccess: (request) => settleRequest(qc, labId, request),
  })
}

export function useApproveRequest(labId: string, requestId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['ApproveInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/requests/{public_id}/approve/', { ...one(labId, requestId), body }))
    },
    meta: { handlesError: true },
    onSuccess: (request) => settleVials(qc, labId, request),
  })
}

export function useRejectRequest(labId: string, requestId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['ReasonInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/requests/{public_id}/reject/', { ...one(labId, requestId), body }))
    },
    meta: { handlesError: true },
    onSuccess: (request) => settleRequest(qc, labId, request),
  })
}

export function useCancelRequest(labId: string, requestId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['ReasonInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/requests/{public_id}/cancel/', { ...one(labId, requestId), body }))
    },
    meta: { handlesError: true },
    onSuccess: (request) => settleVials(qc, labId, request),
  })
}

export function useShipRequest(labId: string, requestId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['ShipInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/requests/{public_id}/ship/', { ...one(labId, requestId), body }))
    },
    meta: { handlesError: true },
    onSuccess: (request) => settleVials(qc, labId, request),
  })
}

/** Step 1 of a regulated request's shipment (#89): nothing leaves, the vials stay reserved. */
export function usePrepareShipment(labId: string, requestId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['ShipInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/requests/{public_id}/prepare-shipment/', { ...one(labId, requestId), body }))
    },
    meta: { handlesError: true },
    onSuccess: (request) => settleRequest(qc, labId, request),
  })
}

/** Step 2: a second person confirms, and the vials leave as with a shipment in one step. */
export function useConfirmShipment(labId: string, requestId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['ConfirmInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/requests/{public_id}/confirm-shipment/', { ...one(labId, requestId), body }))
    },
    meta: { handlesError: true },
    onSuccess: (request) => settleVials(qc, labId, request),
  })
}

export function useWithdrawShipment(labId: string, requestId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['ReasonInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/requests/{public_id}/withdraw-shipment/', { ...one(labId, requestId), body }))
    },
    meta: { handlesError: true },
    onSuccess: (request) => settleRequest(qc, labId, request),
  })
}

export function useRecordAcceptance(labId: string, requestId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ body, file }: { body: AcceptanceBody; file: File }) => {
      await ensureCsrf()
      return unwrap(
        api.POST('/api/v1/labs/{lab_public_id}/requests/{public_id}/acceptances/', {
          ...one(labId, requestId),
          body: { ...body, file: file.name },
          bodySerializer: () => formData(body, file),
        }),
      )
    },
    meta: { handlesError: true },
    onSuccess: (request) => settleRequest(qc, labId, request),
  })
}

type AnswerBody = Omit<Schemas['DepositorAnswerInputRequest'], 'file'>

/** The depositor's answer on a line (#144): a no also rejects the request, which the answer says. */
export function useRecordDepositorAnswer(labId: string, requestId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ body, file }: { body: AnswerBody; file: File | undefined }) => {
      await ensureCsrf()
      return unwrap(
        api.POST('/api/v1/labs/{lab_public_id}/requests/{public_id}/depositor-answers/', {
          ...one(labId, requestId),
          body: { ...body, file: file?.name ?? null },
          bodySerializer: () => {
            const data = new FormData()
            for (const [name, value] of Object.entries(body)) data.append(name, String(value))
            if (file) data.append('file', file)
            return data
          },
        }),
      )
    },
    meta: { handlesError: true },
    onSuccess: (request) => settleRequest(qc, labId, request),
  })
}

export function useCreateRequester(labId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['RequesterInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/requesters/', { ...lab(labId), body }))
    },
    meta: { handlesError: true },
    onSuccess: () => qc.invalidateQueries({ queryKey: requesterKeys.lists(labId) }),
  })
}

export function useUpdateRequester(labId: string, requesterId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['RequesterInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.PUT('/api/v1/labs/{lab_public_id}/requesters/{public_id}/', { ...one(labId, requesterId), body }))
    },
    meta: { handlesError: true },
    // A request shows its requester's institution: those change too.
    onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: requesterKeys.lists(labId) }), qc.invalidateQueries({ queryKey: requestKeys.lab(labId) })]),
  })
}

/** A permit changes what the policy finds on waiting requests: their details are refreshed. */
function settlePermit(qc: QueryClient, labId: string) {
  return Promise.all([qc.invalidateQueries({ queryKey: requesterKeys.lists(labId) }), qc.invalidateQueries({ queryKey: requestKeys.details(labId) })])
}

export function useAddPermit(labId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ body, file }: { body: PermitBody; file: File }) => {
      await ensureCsrf()
      return unwrap(
        api.POST('/api/v1/labs/{lab_public_id}/recipient-permits/', {
          ...lab(labId),
          body: { ...body, file: file.name },
          bodySerializer: () => formData(body, file),
        }),
      )
    },
    meta: { handlesError: true },
    onSuccess: () => settlePermit(qc, labId),
  })
}

export function useEndPermit(labId: string, permitId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['PermitEndInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/recipient-permits/{public_id}/end/', { ...one(labId, permitId), body }))
    },
    meta: { handlesError: true },
    onSuccess: () => settlePermit(qc, labId),
  })
}
