import { zodResolver } from '@hookform/resolvers/zod'
import { useId, useState } from 'react'
import { useForm } from 'react-hook-form'
import { ConfirmDialog, Stack, TextField } from '@/components/ui'
import { errorMessage, isApiError } from '@/lib/api'
import { applyServerErrors } from '@/lib/forms'
import { useCreateDepositor, useUpdateDepositor } from '../api/mutations'
import { type Depositor, type DepositorForm, depositorSchema } from '../schemas'

type Props = {
  labId: string
  /** The depositor to change; none adds a new one. */
  depositor?: Depositor
  open: boolean
  onClose: () => void
  onExited: () => void
  /** The saved depositor, before the dialog closes (the intake picks a new one). */
  onSaved?: (depositor: Depositor) => void
}

const FIELDS = ['name', 'email', 'postal_address', 'institution'] as const

/**
 * Add a depositor or change one. The contact (name, e-mail, address) is personal data: the
 * server keeps it out of the audit trail and records only that a field changed.
 */
export function DepositorDialog({ labId, depositor, open, onClose, onExited, onSaved }: Props) {
  const create = useCreateDepositor(labId)
  const update = useUpdateDepositor(labId, depositor?.public_id ?? '')
  const save = depositor ? update : create
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const { register, handleSubmit, formState, setError } = useForm<DepositorForm>({
    resolver: zodResolver(depositorSchema),
    defaultValues: {
      name: depositor?.name ?? '',
      email: depositor?.email ?? '',
      postal_address: depositor?.postal_address ?? '',
      institution: depositor?.institution ?? '',
    },
  })
  const errors = formState.errors
  const onSubmit = handleSubmit((values) => {
    setFailure(undefined)
    save.mutate(
      { name: values.name.trim(), email: values.email.trim(), postal_address: values.postal_address.trim(), institution: values.institution.trim() },
      {
        onSuccess: (saved) => {
          onSaved?.(saved)
          onClose()
        },
        onError: (error) => {
          if (isApiError(error, 409) && error.code === 'contact_erased') setFailure('This contact was erased. It can no longer be changed.')
          else if (!applyServerErrors(error, FIELDS, setError)) setFailure(errorMessage(error))
        },
      },
    )
  })
  return (
    <ConfirmDialog
      open={open}
      title={depositor ? 'Change the depositor' : 'Add a depositor'}
      description="The contact is personal data: the audit trail records only that it changed, never its values."
      confirmLabel={depositor ? 'Save the depositor' : 'Add the depositor'}
      form={formId}
      pending={save.isPending}
      error={failure ?? errors.root?.server?.message}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label="Depositor" spacing={2} sx={{ mt: 2 }}>
        {/* oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog) */}
        <TextField label="Name" autoFocus autoComplete="off" error={errors.name?.message} {...register('name')} />
        <TextField label="E-mail" type="email" autoComplete="off" error={errors.email?.message} {...register('email')} />
        <TextField label="Postal address" multiline minRows={2} autoComplete="off" error={errors.postal_address?.message} {...register('postal_address')} />
        <TextField label="Institution" hint="The organisation the depositor deposits for. Empty for a private person." autoComplete="off" error={errors.institution?.message} {...register('institution')} />
      </Stack>
    </ConfirmDialog>
  )
}
