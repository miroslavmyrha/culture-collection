import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, ensureCsrf, unwrap } from '@/lib/api'
import { sharedKeys } from '@/lib/shared-keys'
import type { AddMemberInput, Role } from '../schemas'
import { labKeys } from './keys'

// Each form or dialog shows its own failure (meta.handlesError), so the global message stays
// quiet. onSuccess returns the invalidation: the mutation stays pending until the data is fresh.
// A location grant decides whether a vial offers "Reveal location" (can_reveal) to its holder,
// and a manager may grant or revoke their own, so both also invalidate the lab's material (shared
// keys). Removing a member ends their grant too, but they lose the lab with it: nothing of it
// stays on their screen to refresh.

export function useAddMember(labId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: AddMemberInput) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/members/', { params: { path: { lab_public_id: labId } }, body: input }))
    },
    meta: { handlesError: true },
    onSuccess: () => qc.invalidateQueries({ queryKey: labKeys.all }),
  })
}

export function useChangeRole(labId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ memberId, role }: { memberId: string; role: Role }) => {
      await ensureCsrf()
      return unwrap(
        api.PATCH('/api/v1/labs/{lab_public_id}/members/{public_id}/', {
          params: { path: { lab_public_id: labId, public_id: memberId } },
          body: { role },
        }),
      )
    },
    meta: { handlesError: true },
    onSuccess: () => qc.invalidateQueries({ queryKey: labKeys.all }),
  })
}

export function useRemoveMember(labId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (memberId: string) => {
      await ensureCsrf()
      await unwrap(
        api.DELETE('/api/v1/labs/{lab_public_id}/members/{public_id}/', {
          params: { path: { lab_public_id: labId, public_id: memberId } },
        }),
      )
    },
    meta: { handlesError: true },
    onSuccess: () => qc.invalidateQueries({ queryKey: labKeys.all }),
  })
}

export function useGrantLocation(labId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: { member: string; reason: string }) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/labs/{lab_public_id}/location-grants/', { params: { path: { lab_public_id: labId } }, body }))
    },
    meta: { handlesError: true },
    onSuccess: () =>
      Promise.all([qc.invalidateQueries({ queryKey: labKeys.locationGrants(labId) }), qc.invalidateQueries({ queryKey: sharedKeys.material(labId) })]),
  })
}

export function useRevokeLocation(labId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ grantId, reason }: { grantId: string; reason: string }) => {
      await ensureCsrf()
      await unwrap(
        api.POST('/api/v1/labs/{lab_public_id}/location-grants/{public_id}/revoke/', {
          params: { path: { lab_public_id: labId, public_id: grantId } },
          body: { reason },
        }),
      )
    },
    meta: { handlesError: true },
    onSuccess: () =>
      Promise.all([qc.invalidateQueries({ queryKey: labKeys.locationGrants(labId) }), qc.invalidateQueries({ queryKey: sharedKeys.material(labId) })]),
  })
}
