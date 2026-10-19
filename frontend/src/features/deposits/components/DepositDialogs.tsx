import { zodResolver } from '@hookform/resolvers/zod'
import { useId, useState } from 'react'
import { FormProvider, useForm } from 'react-hook-form'
import { ConfirmDialog, Stack, TextField } from '@/components/ui'
import { errorMessage, isApiError } from '@/lib/api'
import { applyServerErrors } from '@/lib/forms'
import { useRejectDeposit, useReplaceTerms } from '../api/mutations'
import { type Deposit, type RejectForm, rejectSchema, type ReplaceTermsForm, replaceTermsSchema, type ReplaceTermsValues, termsBody, termsForm } from '../schemas'
import { TERMS_FIELDS, TermsFields } from './TermsFields'

type Common = { labId: string; deposit: Deposit; open: boolean; onClose: () => void; onExited: () => void }

const REASON_HINT = 'Stored for good with the decision. Name no person.'
const missing = { type: 'server', message: 'Say why' } as const

/** A request that failed because someone else acted first: the dialog says so in its words. */
function stateError(error: unknown): string | undefined {
  if (isApiError(error, 409) && error.code === 'deposit_state') return 'The deposit changed meanwhile. Close this and look at it again.'
  if (isApiError(error, 409) && error.code === 'terms_changed') return 'The terms changed at the same moment. Close this and look at them again.'
  return undefined
}

export function RejectDialog({ labId, deposit, open, onClose, onExited }: Common) {
  const reject = useRejectDeposit(labId, deposit.public_id)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const { register, handleSubmit, formState, setError } = useForm<RejectForm>({ resolver: zodResolver(rejectSchema), defaultValues: { reason: '' } })
  const onSubmit = handleSubmit((values) => {
    setFailure(undefined)
    reject.mutate(
      { reason: values.reason.trim() },
      {
        onSuccess: onClose,
        onError: (error) => {
          if (isApiError(error) && error.code === 'reason_required') setError('reason', missing, { shouldFocus: true })
          else setFailure(stateError(error) ?? (applyServerErrors(error, ['reason'], setError) ? undefined : errorMessage(error)))
        },
      },
    )
  })
  return (
    <ConfirmDialog
      open={open}
      destructive
      title={`Reject ${deposit.name_as_received}?`}
      description="The deposit ends here and becomes no strain. The decision cannot be undone; a new deposit of the material starts again from receipt."
      confirmLabel="Reject the deposit"
      form={formId}
      pending={reject.isPending}
      error={failure}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label="Rejection" spacing={2} sx={{ mt: 2 }}>
        <TextField label="Reason" hint={REASON_HINT} multiline minRows={2} error={formState.errors.reason?.message} {...register('reason')} />
      </Stack>
    </ConfirmDialog>
  )
}

export function ReplaceTermsDialog({ labId, deposit, open, onClose, onExited }: Common) {
  const replace = useReplaceTerms(labId, deposit.public_id)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const form = useForm<ReplaceTermsForm, unknown, ReplaceTermsValues>({
    resolver: zodResolver(replaceTermsSchema),
    defaultValues: { terms: termsForm(deposit.terms), reason: '' },
  })
  const { register, handleSubmit, formState, setError } = form
  const onSubmit = handleSubmit((values) => {
    setFailure(undefined)
    replace.mutate(
      { terms: termsBody(values.terms), reason: values.reason.trim() },
      {
        onSuccess: onClose,
        onError: (error) => {
          if (isApiError(error) && error.code === 'reason_required') setError('reason', missing, { shouldFocus: true })
          else setFailure(stateError(error) ?? (applyServerErrors(error, [...TERMS_FIELDS, 'reason'], setError) ? undefined : errorMessage(error)))
        },
      },
    )
  })
  return (
    <ConfirmDialog
      open={open}
      title="Change the terms"
      description={`This adds version ${deposit.terms.version + 1}, which applies from now on. Version ${deposit.terms.version} stays in the history as it was.`}
      confirmLabel="Save the new version"
      form={formId}
      pending={replace.isPending}
      error={failure}
      onClose={onClose}
      onExited={onExited}
    >
      <FormProvider {...form}>
        <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label="New terms" spacing={2} sx={{ mt: 2 }}>
          <TermsFields labId={labId} />
          <TextField label="Reason" hint="Why the terms change. Stored for good: name no person." multiline minRows={2} error={formState.errors.reason?.message} {...register('reason')} />
        </Stack>
      </FormProvider>
    </ConfirmDialog>
  )
}
