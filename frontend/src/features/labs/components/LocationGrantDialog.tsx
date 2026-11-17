import { zodResolver } from '@hookform/resolvers/zod'
import { useId, useState } from 'react'
import { useForm } from 'react-hook-form'
import { ConfirmDialog, Stack, TextField } from '@/components/ui'
import { isApiError } from '@/lib/api'
import { applyServerErrors } from '@/lib/forms'
import { useConfirmLocation, useGrantLocation, useRevokeLocation } from '../api/mutations'
import { type LocationGrant, type LocationGrantInput, locationGrantSchema, type Member } from '../schemas'
import { memberError } from './memberErrors'

type Props = {
  labId: string
  member: Member
  step: GrantStep
  /** The member's open grant: the one confirmed, withdrawn or revoked. */
  grant: LocationGrant | undefined
  open: boolean
  onClose: () => void
  onExited: () => void
}

const TEXTS = {
  grant: {
    title: (u: string) => `Propose that ${u} see regulated locations`,
    description: 'Another manager confirms it before they may reveal where vials of regulated strains are stored, one vial at a time. Every reveal is recorded.',
    confirm: 'Propose',
  },
  confirm: {
    title: (u: string) => `Confirm that ${u} may see regulated locations`,
    description: 'From now on they may reveal where vials of regulated strains are stored, one vial at a time. Every reveal is recorded.',
    confirm: 'Confirm',
  },
  withdraw: {
    title: (u: string) => `Withdraw the proposal for ${u}`,
    description: 'The proposal ends without ever revealing anything.',
    confirm: 'Withdraw',
  },
  revoke: {
    title: (u: string) => `Stop ${u} seeing regulated locations`,
    description: 'From now on the places of regulated strains stay hidden from them.',
    confirm: 'Revoke',
  },
} as const

export type GrantStep = keyof typeof TEXTS

/** What the location button of a member does: propose, or end what is open (#267). */
export const endStep = (grant: LocationGrant): GrantStep => (grant.confirmed_at ? 'revoke' : 'withdraw')

/**
 * Proposes that a member see where the lab's regulated strains are stored, confirms a proposal
 * as a second manager (#267), or ends it, each with a reason the history keeps (ADR 0009). No
 * role carries it.
 */
export function LocationGrantDialog({ labId, member, step, grant, open, onClose, onExited }: Props) {
  const add = useGrantLocation(labId)
  const revoke = useRevokeLocation(labId)
  const confirm = useConfirmLocation(labId)
  const text = TEXTS[step]
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
    const done = { onSuccess: onClose, onError: failed }
    if (!grant) add.mutate({ member: member.public_id, reason: reason.trim() }, done)
    else if (step === 'confirm') confirm.mutate({ grantId: grant.public_id, reason: reason.trim() }, done)
    else revoke.mutate({ grantId: grant.public_id, reason: reason.trim() }, done)
  })
  return (
    <ConfirmDialog
      open={open}
      title={text.title(member.username)}
      description={text.description}
      confirmLabel={text.confirm}
      form={formId}
      pending={add.isPending || revoke.isPending || confirm.isPending}
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
