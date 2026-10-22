import { zodResolver } from '@hookform/resolvers/zod'
import { useId, useState } from 'react'
import { type UseFormRegisterReturn, useForm } from 'react-hook-form'
import { CheckboxField, ConfirmDialog, SelectField, Stack, TextField, Typography } from '@/components/ui'
import { errorMessage, isApiError } from '@/lib/api'
import { applyServerErrors } from '@/lib/forms'
import { useApproveRequest, useCancelRequest, useRecordAcceptance, useRejectRequest } from '../api/mutations'
import {
  type AcceptanceForm,
  acceptanceSchema,
  type AcceptanceValues,
  type ApproveForm,
  approveSchema,
  type DecisionForm,
  decisionSchema,
  options,
  type Request,
  SIGNER_ROLE_LABELS,
  SIGNER_ROLES,
} from '../schemas'

type Common = { labId: string; request: Request; open: boolean; onClose: () => void; onExited: () => void }

const REASON_HINT = 'Stored for good with the decision. Name no person.'
const missing = { type: 'server', message: 'Say why' } as const
const today = () => new Date().toLocaleDateString('sv')

/** A request that failed because someone else acted first, or the policy stopped it. */
function stateError(error: unknown): string | undefined {
  if (isApiError(error, 409) && error.code === 'request_state') return 'The request changed meanwhile. Close this and look at it again.'
  if (isApiError(error, 409) && error.code === 'not_enough_vials') return 'Fewer vials are free than the request asks for. Close this and look at it again.'
  if (isApiError(error, 409) && error.code === 'vial_reserved_meanwhile') return 'A vial was reserved at the same moment. Try again.'
  if (isApiError(error, 422) && error.code === 'request_blocked') return 'Something blocks the approval now. Close this and read what stands in the way.'
  if (isApiError(error, 403) && error.code === 'manager_approval_required') return 'A manager approves this request.'
  return undefined
}

export function ApproveDialog({ labId, request, open, onClose, onExited }: Common) {
  const approve = useApproveRequest(labId, request.public_id)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const needsManager = request.findings.some((f) => f.severity === 'manager')
  const { register, handleSubmit, formState, setError } = useForm<ApproveForm>({ resolver: zodResolver(approveSchema), defaultValues: { reason: '' } })
  const onSubmit = handleSubmit((values) => {
    if (needsManager && !values.reason.trim()) {
      setError('reason', { type: 'manual', message: 'Say why the findings allow it' }, { shouldFocus: true })
      return
    }
    setFailure(undefined)
    approve.mutate(
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
  const vials = request.lines.reduce((sum, line) => sum + line.quantity, 0)
  return (
    <ConfirmDialog
      open={open}
      title={`Approve request ${request.number}?`}
      description={`${vials === 1 ? 'One vial is' : `${vials} vials are`} reserved for it until the shipment or a cancellation.${needsManager ? ' A finding needs a manager: say why it allows the approval.' : ''}`}
      confirmLabel="Approve and reserve"
      form={formId}
      pending={approve.isPending}
      error={failure}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label="Approval" spacing={2} sx={{ mt: 2 }}>
        {/* oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog) */}
        <TextField label={needsManager ? 'Reason' : 'Reason (optional)'} autoFocus hint={REASON_HINT} multiline minRows={2} error={formState.errors.reason?.message} {...register('reason')} />
      </Stack>
    </ConfirmDialog>
  )
}

function ReasonDialog({
  open,
  title,
  description,
  confirmLabel,
  label,
  pending,
  mutate,
  onClose,
  onExited,
}: {
  open: boolean
  title: string
  description: string
  confirmLabel: string
  label: string
  pending: boolean
  mutate: (reason: string, callbacks: { onSuccess: () => void; onError: (error: unknown) => void }) => void
  onClose: () => void
  onExited: () => void
}) {
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const { register, handleSubmit, formState, setError } = useForm<DecisionForm>({ resolver: zodResolver(decisionSchema), defaultValues: { reason: '' } })
  const onSubmit = handleSubmit((values) => {
    setFailure(undefined)
    mutate(values.reason.trim(), {
      onSuccess: onClose,
      onError: (error) => {
        if (isApiError(error) && error.code === 'reason_required') setError('reason', missing, { shouldFocus: true })
        else setFailure(stateError(error) ?? (applyServerErrors(error, ['reason'], setError) ? undefined : errorMessage(error)))
      },
    })
  })
  return (
    <ConfirmDialog open={open} destructive title={title} description={description} confirmLabel={confirmLabel} form={formId} pending={pending} error={failure} onClose={onClose} onExited={onExited}>
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label={label} spacing={2} sx={{ mt: 2 }}>
        <TextField label="Reason" hint={REASON_HINT} multiline minRows={2} error={formState.errors.reason?.message} {...register('reason')} />
      </Stack>
    </ConfirmDialog>
  )
}

export function RejectDialog({ labId, request, open, onClose, onExited }: Common) {
  const reject = useRejectRequest(labId, request.public_id)
  return (
    <ReasonDialog
      open={open}
      title={`Reject request ${request.number}?`}
      description="The request is refused and kept with the reason. Nothing is reserved; a new request starts again."
      confirmLabel="Reject the request"
      label="Rejection"
      pending={reject.isPending}
      mutate={(reason, callbacks) => reject.mutate({ reason }, callbacks)}
      onClose={onClose}
      onExited={onExited}
    />
  )
}

export function CancelDialog({ labId, request, open, onClose, onExited }: Common) {
  const cancel = useCancelRequest(labId, request.public_id)
  const reserved = request.lines.reduce((sum, line) => sum + line.reserved.length, 0)
  return (
    <ReasonDialog
      open={open}
      title={`Cancel request ${request.number}?`}
      description={
        reserved > 0
          ? `The request is withdrawn and its ${reserved === 1 ? 'reserved vial is' : `${reserved} reserved vials are`} available again. It cannot be undone.`
          : 'The request is withdrawn and kept with the reason. It cannot be undone.'
      }
      confirmLabel="Cancel the request"
      label="Cancellation"
      pending={cancel.isPending}
      mutate={(reason, callbacks) => cancel.mutate({ reason }, callbacks)}
      onClose={onClose}
      onExited={onExited}
    />
  )
}

const FIELDS = ['mta', 'signer_name', 'signer_email', 'signer_role', 'authorised_signatory', 'accepted_on', 'file'] as const

/** The requester's acceptance of an MTA version a line is pinned to, from the signed copy. */
export function AcceptanceDialog({ labId, request, open, onClose, onExited }: Common) {
  const record = useRecordAcceptance(labId, request.public_id)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const mtas = [...new Map(request.lines.flatMap((l) => (l.mta ? [[l.mta.public_id, l.mta] as const] : []))).values()]
  const { register, handleSubmit, formState, setError } = useForm<AcceptanceForm, unknown, AcceptanceValues>({
    resolver: zodResolver(acceptanceSchema),
    defaultValues: {
      mta: mtas.length === 1 ? (mtas[0]?.public_id ?? '') : '',
      signer_name: '',
      signer_email: '',
      signer_role: '',
      authorised_signatory: false,
      accepted_on: today(),
      file: null,
    },
  })
  const errors = formState.errors
  const onSubmit = handleSubmit((values) => {
    if (record.isPending) return
    setFailure(undefined)
    record.mutate(
      {
        body: {
          mta: values.mta,
          signer_name: values.signer_name.trim(),
          signer_email: values.signer_email.trim(),
          signer_role: values.signer_role,
          authorised_signatory: values.authorised_signatory,
          accepted_on: values.accepted_on,
        },
        file: values.file,
      },
      {
        onSuccess: onClose,
        onError: (error) => {
          if (isApiError(error, 409) && error.code === 'acceptance_exists') setFailure('An acceptance of this MTA version is recorded already.')
          else setFailure(stateError(error) ?? (applyServerErrors(error, FIELDS, setError) ? undefined : errorMessage(error)))
        },
      },
    )
  })
  return (
    <ConfirmDialog
      open={open}
      title="Record an acceptance of the MTA"
      description="From the signed copy the requester sent. The copy is kept as the evidence; the signer is personal data and the audit trail records only that it was set."
      confirmLabel="Record the acceptance"
      form={formId}
      pending={record.isPending}
      error={failure ?? errors.root?.server?.message}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label="Acceptance" spacing={2} sx={{ mt: 2 }}>
        <SelectField
          label="MTA version"
          options={[{ value: '', label: 'Choose' }, ...mtas.map((m) => ({ value: m.public_id, label: `${m.code} version ${m.version}: ${m.title}` }))]}
          error={errors.mta?.message}
          {...register('mta')}
        />
        <TextField label="Signed by" autoComplete="off" error={errors.signer_name?.message} {...register('signer_name')} />
        <TextField label="Signer's e-mail" type="email" autoComplete="off" error={errors.signer_email?.message} {...register('signer_email')} />
        <SelectField label="Signer's role" options={[{ value: '', label: 'Choose' }, ...options(SIGNER_ROLE_LABELS, SIGNER_ROLES)]} error={errors.signer_role?.message} {...register('signer_role')} />
        <CheckboxField label="The signer may bind the institution" {...register('authorised_signatory')} />
        <TextField label="Accepted on" hint="YYYY-MM-DD" autoComplete="off" error={errors.accepted_on?.message} {...register('accepted_on')} />
        <FileField label="Signed copy" error={errors.file?.message} {...register('file')} />
      </Stack>
    </ConfirmDialog>
  )
}

/** A file input with its label and error wired like the other fields. PDF, PNG or JPEG.
 * Spread register('file') on it: react-hook-form reads its FileList and focuses it. */
export function FileField({ label, error, ref, ...props }: { label: string; error?: string | undefined; ref?: React.Ref<HTMLInputElement> } & UseFormRegisterReturn) {
  const id = useId()
  const hint = `${id}-hint`
  return (
    <Stack spacing={0.5}>
      <Typography component="label" htmlFor={id}>
        {label}
      </Typography>
      <input {...props} id={id} ref={ref} type="file" accept="application/pdf,image/png,image/jpeg" aria-describedby={hint} aria-invalid={error !== undefined} />
      <Typography id={hint} variant="body2" color={error ? 'error' : 'text.secondary'}>
        {['PDF, PNG or JPEG, at most 10 MB.', error].filter(Boolean).join(' ')}
      </Typography>
    </Stack>
  )
}
