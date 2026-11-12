import { zodResolver } from '@hookform/resolvers/zod'
import { useId, useState } from 'react'
import { type FieldErrors, type UseFormRegister, useForm } from 'react-hook-form'
import { ConfirmDialog, Stack, TextField } from '@/components/ui'
import { errorMessage, isApiError } from '@/lib/api'
import { applyServerErrors } from '@/lib/forms'
import { useCreateMedium, useRetireMedium, useUpdateMedium } from '../api/mutations'
import { type Medium, type MediumForm, mediumSchema, type RetireForm, retireSchema } from '../schemas'

type Common = { labId: string; open: boolean; onClose: () => void; onExited: () => void }

const REASON_HINT = 'Stored for good with the change. Name no person.'

/** The message a medium dialog owns for a failure, by the problem code. */
export function mediumError(error: unknown): string {
  if (isApiError(error, 409) && error.code === 'medium_retired') return 'This medium is retired. Close this and reload the list.'
  return errorMessage(error)
}

const FIELDS = ['name', 'composition_reference'] as const

/** What the dialog says for a new medium and for an existing one. */
const TEXTS = {
  new: {
    title: 'Add a medium',
    description: 'A medium joins the lab list. It is never deleted, only retired.',
    confirm: 'Add medium',
    form: 'New medium',
  },
  edit: {
    title: (medium: Medium) => `Edit ${medium.name}`,
    description: 'The name and the reference change for every strain and passage that uses this medium. The change is in the audit trail.',
    confirm: 'Save medium',
    form: 'Medium',
  },
}

const defaultsOf = (medium: Medium | undefined): MediumForm => ({ name: medium?.name ?? '', composition_reference: medium?.composition_reference ?? '' })

type FieldsProps = { register: UseFormRegister<MediumForm>; errors: FieldErrors<MediumForm> }

/** The name and where the recipe is written down. */
function MediumFields({ register, errors }: FieldsProps) {
  return (
    <>
      <TextField
        label="Name"
        hint="For example LB or Nutrient agar."
        autoComplete="off"
        // oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog)
        autoFocus
        error={errors.name?.message}
        {...register('name')}
      />
      <TextField
        label="Composition reference"
        hint="Where the recipe is written down, for example DSMZ medium 1. Optional."
        autoComplete="off"
        error={errors.composition_reference?.message}
        {...register('composition_reference')}
      />
    </>
  )
}

/** A new medium (no `medium`) or the name and reference of an existing one. */
export function MediumDialog({ labId, medium, open, onClose, onExited }: Common & { medium?: Medium }) {
  const create = useCreateMedium(labId)
  const update = useUpdateMedium(labId, medium?.public_id ?? '')
  const save = medium ? update : create
  const texts = medium ? TEXTS.edit : TEXTS.new
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const { register, handleSubmit, formState, setError } = useForm<MediumForm>({ resolver: zodResolver(mediumSchema), defaultValues: defaultsOf(medium) })
  const onSubmit = handleSubmit((values) => {
    setFailure(undefined)
    save.mutate(values, {
      onSuccess: onClose,
      onError: (error) => setFailure(applyServerErrors(error, FIELDS, setError) ? undefined : mediumError(error)),
    })
  })
  return (
    <ConfirmDialog
      open={open}
      title={medium ? TEXTS.edit.title(medium) : TEXTS.new.title}
      description={texts.description}
      confirmLabel={texts.confirm}
      form={formId}
      pending={save.isPending}
      error={failure ?? formState.errors.root?.server?.message}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label={texts.form} spacing={2} sx={{ mt: 2 }}>
        <MediumFields register={register} errors={formState.errors} />
      </Stack>
    </ConfirmDialog>
  )
}

export function RetireMediumDialog({ labId, medium, open, onClose, onExited }: Common & { medium: Medium }) {
  const retire = useRetireMedium(labId, medium.public_id)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const { register, handleSubmit, formState, setError } = useForm<RetireForm>({ resolver: zodResolver(retireSchema), defaultValues: { reason: '' } })
  const onSubmit = handleSubmit((values) => {
    setFailure(undefined)
    retire.mutate(
      { reason: values.reason },
      {
        onSuccess: onClose,
        onError: (error) => {
          if (isApiError(error) && error.code === 'reason_required') setError('reason', { type: 'server', message: 'Say why' }, { shouldFocus: true })
          else setFailure(applyServerErrors(error, ['reason'], setError) ? undefined : mediumError(error))
        },
      },
    )
  })
  return (
    <ConfirmDialog
      open={open}
      title={`Retire ${medium.name}?`}
      description="A retired medium stays on the strains and passages that use it, and cannot be chosen for new ones. It is never deleted."
      confirmLabel="Retire medium"
      destructive
      form={formId}
      pending={retire.isPending}
      error={failure}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label="Retire medium" spacing={2} sx={{ mt: 2 }}>
        <TextField label="Reason" hint={REASON_HINT} multiline minRows={2} error={formState.errors.reason?.message} {...register('reason')} />
      </Stack>
    </ConfirmDialog>
  )
}
