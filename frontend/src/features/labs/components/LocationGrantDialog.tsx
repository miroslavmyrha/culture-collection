import { zodResolver } from '@hookform/resolvers/zod'
import { useId, useState } from 'react'
import { useForm } from 'react-hook-form'
import { ConfirmDialog, Stack, TextField } from '@/components/ui'
import { isApiError } from '@/lib/api'
import { applyServerErrors } from '@/lib/forms'
import { useGrantLocation, useRevokeLocation } from '../api/mutations'
import { type LocationGrant, type LocationGrantInput, locationGrantSchema, type Member } from '../schemas'
import { memberError } from './memberErrors'

type Props = {
  labId: string
  member: Member
  /** The member's open grant: given, the dialog revokes it; absent, it grants one. */
  grant: LocationGrant | undefined
  open: boolean
  onClose: () => void
  onExited: () => void
}

/**
 * Lets a member see where the lab's regulated strains are stored, or takes it back, with a
 * reason the history keeps (ADR 0009). No role carries it.
 */
export function LocationGrantDialog({ labId, member, grant, open, onClose, onExited }: Props) {
  const add = useGrantLocation(labId)
  const revoke = useRevokeLocation(labId)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const { register, handleSubmit, formState, setError } = useForm<LocationGrantInput>({
    resolver: zodResolver(locationGrantSchema),
    defaultValues: { reason: '' },
  })
  const failed = (error: unknown) => {
    if (isApiError(error) && error.code === 'reason_required') {
      setError('reason', { type: 'server', message: 'Say why' }, { shouldFocus: true })
      return
    }
    // already_granted names the member, a field this dialog does not show: its own message.
    if (isApiError(error) && error.code === 'already_granted') {
      setFailure(memberError(error))
      return
    }
    setFailure(applyServerErrors(error, ['reason'], setError) ? undefined : memberError(error))
  }
  const onSubmit = handleSubmit(({ reason }) => {
    setFailure(undefined)
    if (grant) revoke.mutate({ grantId: grant.public_id, reason: reason.trim() }, { onSuccess: onClose, onError: failed })
    else add.mutate({ member: member.public_id, reason: reason.trim() }, { onSuccess: onClose, onError: failed })
  })
  return (
    <ConfirmDialog
      open={open}
      title={grant ? `Stop ${member.username} seeing regulated locations` : `Let ${member.username} see regulated locations`}
      description={
        grant
          ? 'From now on the places of regulated strains stay hidden from them.'
          : 'They may reveal where vials of regulated strains are stored, one vial at a time. Every reveal is recorded.'
      }
      confirmLabel={grant ? 'Revoke' : 'Grant'}
      form={formId}
      pending={add.isPending || revoke.isPending}
      error={failure ?? formState.errors.root?.server?.message}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label="Reason" spacing={2} sx={{ mt: 2 }}>
        <TextField
          label="Reason"
          hint="Stored for good with the change. Name no person."
          multiline
          minRows={2}
          // oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog)
          autoFocus
          error={formState.errors.reason?.message}
          {...register('reason')}
        />
      </Stack>
    </ConfirmDialog>
  )
}
