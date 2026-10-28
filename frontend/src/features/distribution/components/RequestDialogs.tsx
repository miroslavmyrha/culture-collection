import { zodResolver } from '@hookform/resolvers/zod'
import { useId, useState } from 'react'
import { type UseFormRegisterReturn, useForm, useWatch } from 'react-hook-form'
import { CheckboxField, ConfirmDialog, SelectField, Stack, TextField, Typography } from '@/components/ui'
import { errorMessage, isApiError, readProblem } from '@/lib/api'
import { applyServerErrors } from '@/lib/forms'
import {
  useApproveRequest,
  useCancelRequest,
  useConfirmShipment,
  usePrepareShipment,
  useRecordAcceptance,
  useRecordDepositorAnswer,
  useRejectRequest,
  useShipRequest,
  useWithdrawShipment,
} from '../api/mutations'
import {
  type AcceptanceForm,
  acceptanceSchema,
  type AcceptanceValues,
  type ApproveForm,
  approveSchema,
  BASES,
  BASIS_LABELS,
  COOLANT_LABELS,
  COOLANTS,
  type DecisionForm,
  decisionSchema,
  type DepositorAnswerForm,
  depositorAnswerSchema,
  type DepositorAnswerValues,
  type Line,
  type Preparation,
  isTransportClass,
  options,
  PACKING_INSTRUCTIONS,
  PACKING_LABELS,
  type Request,
  SIGNER_ROLE_LABELS,
  SIGNER_ROLES,
  type ShipForm,
  shipSchema,
  type ShipValues,
  TRANSPORT_CLASS_LABELS,
  TRANSPORT_CLASSES,
  USE_LABELS,
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
  if (isApiError(error, 422) && error.code === 'second_person_required') return SECOND_PERSON
  if (isApiError(error, 422) && error.code === 'ship_in_one_step') return 'No strain of this request is regulated: close this and ship it in one step.'
  if (isApiError(error, 422) && error.code === 'shipment_blocked') return `Nothing is shipped. ${readProblem(error.body)?.detail ?? ''}`.trim()
  if (isApiError(error, 403) && error.code === 'confirm_own_approval') return 'You approved this request, so a different person confirms its shipment.'
  if (isApiError(error, 403) && error.code === 'confirm_own_preparation') return 'You prepared this shipment, so a different person confirms it.'
  if (isApiError(error, 409) && error.code === 'preparation_changed') return 'The prepared shipment changed meanwhile. Close this and read it again.'
  if (isApiError(error, 409) && error.code === 'preparation_exists') return 'Someone prepared this shipment at the same moment. Close this and look at it again.'
  return undefined
}

/** How a regulated request leaves (ADR 0009, the two-person rule). */
export const SECOND_PERSON = 'A regulated strain leaves in two steps: one person prepares the shipment, and a second person, neither the approver nor the preparer, confirms it.'


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

const ANSWER_FIELDS = ['line', 'answered_on', 'note', 'file'] as const

/**
 * What the depositor answered for strains whose terms leave the request's use on request (#144),
 * from the depositor's letter or e-mail (the file) and/or a note. A yes lets the strain pass that
 * gate; a no rejects the whole request with the answer as the reason, so its dialog is an
 * alertdialog that opens on Cancel. Recorded once per strain, never changed.
 */
export function DepositorAnswerDialog({ labId, request, lines, agreed, open, onClose, onExited }: Common & { lines: Line[]; agreed: boolean }) {
  const record = useRecordDepositorAnswer(labId, request.public_id)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const use = USE_LABELS[request.use].toLowerCase()
  const { register, handleSubmit, formState, setError } = useForm<DepositorAnswerForm, unknown, DepositorAnswerValues>({
    resolver: zodResolver(depositorAnswerSchema),
    defaultValues: { line: lines.length === 1 ? (lines[0]?.public_id ?? '') : '', answered_on: today(), note: '', file: null },
  })
  const errors = formState.errors
  const onSubmit = handleSubmit((values) => {
    if (record.isPending) return
    setFailure(undefined)
    record.mutate(
      { body: { line: values.line, agreed, answered_on: values.answered_on, note: values.note.trim() }, file: values.file },
      {
        onSuccess: onClose,
        onError: (error) => {
          if (isApiError(error, 409) && error.code === 'depositor_answer_exists') setFailure('The depositor’s answer for this strain is recorded already. Close this and look at it again.')
          else setFailure(stateError(error) ?? (applyServerErrors(error, ANSWER_FIELDS, setError) ? undefined : errorMessage(error)))
        },
      },
    )
  })
  return (
    <ConfirmDialog
      open={open}
      destructive={!agreed}
      title={agreed ? 'Record the depositor’s yes' : `Record the depositor’s no and reject request ${request.number}?`}
      description={
        agreed
          ? `The depositor agreed to ${use}: the strain may go out for it once nothing else stands in the way. The answer is kept for good and cannot be changed.`
          : `The depositor declined ${use}: request ${request.number} is rejected with the answer as the reason. It cannot be undone; a new request for other strains starts again.`
      }
      confirmLabel={agreed ? 'Record the yes' : 'Record the no and reject'}
      form={formId}
      pending={record.isPending}
      error={failure}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label="Depositor’s answer" spacing={2} sx={{ mt: 2 }}>
        <SelectField
          label="Strain"
          options={[{ value: '', label: 'Choose' }, ...lines.map((l) => ({ value: l.public_id, label: `${l.strain.accession_number ?? ''}, ${l.strain.taxon}` }))]}
          error={errors.line?.message}
          {...register('line')}
        />
        <TextField label="Answered on" hint="YYYY-MM-DD, the day the depositor gave the answer" autoComplete="off" error={errors.answered_on?.message} {...register('answered_on')} />
        <TextField label="Note" hint="What the depositor said, and how. Stored for good: name no person." multiline minRows={2} error={errors.note?.message} {...register('note')} />
        <FileField label="Depositor’s letter or e-mail" error={errors.file?.message} {...register('file')} />
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

const SHIP_FIELDS = [
  'transport_class',
  'classification_basis',
  'basis_note',
  'packing_instruction',
  'coolant',
  'coolant_kg',
  'responsible_name',
  'responsible_phone',
  'carrier',
  'tracking_number',
] as const

/**
 * The shipper's record of the package (WHO transport guidance, 2.1: the shipper classifies):
 * the class with its basis, the packing (P650 for UN 3373, filled when it is chosen), the
 * coolant, who answers the phone about it, and the carrier. Every reserved vial goes at once.
 * With `prepare` the same record is step 1 of a regulated request (#89): nothing leaves until a
 * second person confirms it.
 */
export function ShipDialog({ labId, request, open, onClose, onExited, prepare = false }: Common & { prepare?: boolean }) {
  const shipNow = useShipRequest(labId, request.public_id)
  const prepared = usePrepareShipment(labId, request.public_id)
  const ship = prepare ? prepared : shipNow
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const { register, handleSubmit, formState, setError, setValue, control } = useForm<ShipForm, unknown, ShipValues>({
    resolver: zodResolver(shipSchema),
    defaultValues: {
      transport_class: 'not_subject',
      classification_basis: '',
      basis_note: '',
      packing_instruction: 'triple_packaging',
      coolant: '',
      coolant_kg: '',
      responsible_name: '',
      responsible_phone: '',
      carrier: '',
      tracking_number: '',
    },
  })
  const errors = formState.errors
  const chosen = useWatch({ control, name: 'transport_class' })
  const bases = isTransportClass(chosen) ? BASES[chosen] : []
  const transportClass = register('transport_class', {
    onChange: (event: { target: { value: string } }) => {
      setValue('classification_basis', '')
      if (event.target.value === 'un3373') setValue('packing_instruction', 'p650')
    },
  })
  const onSubmit = handleSubmit((values) => {
    if (ship.isPending) return
    setFailure(undefined)
    ship.mutate(
      {
        transport_class: values.transport_class,
        classification_basis: values.classification_basis,
        basis_note: values.basis_note,
        packing_instruction: values.packing_instruction,
        coolant: values.coolant,
        coolant_kg: values.coolant_kg ? values.coolant_kg.replace(',', '.') : null,
        responsible_name: values.responsible_name,
        responsible_phone: values.responsible_phone.trim(),
        carrier: values.carrier,
        tracking_number: values.tracking_number,
      },
      {
        onSuccess: onClose,
        onError: (error) => setFailure(stateError(error) ?? (applyServerErrors(error, SHIP_FIELDS, setError) ? undefined : errorMessage(error))),
      },
    )
  })
  const vials = request.lines.reduce((sum, line) => sum + line.reserved.length, 0)
  return (
    <ConfirmDialog
      open={open}
      title={prepare ? `Prepare the shipment of request ${request.number}?` : `Ship request ${request.number}?`}
      description={
        prepare
          ? `Nothing leaves yet: ${vials === 1 ? 'its reserved vial stays' : `its ${vials} reserved vials stay`} reserved until a second person, neither the approver nor you, confirms the shipment. The gates are checked today and again on the day it is confirmed.`
          : `${vials === 1 ? 'Its reserved vial leaves' : `All ${vials} reserved vials leave`} the collection today: recorded as distributed and out of their boxes. A shipment cannot be undone. The gates are checked again on today’s date.`
      }
      confirmLabel={prepare ? 'Prepare' : 'Ship'}
      form={formId}
      pending={ship.isPending}
      error={failure}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label={prepare ? 'Prepared shipment' : 'Shipment'} spacing={2} sx={{ mt: 2 }}>
        {/* oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog) */}
        <SelectField label="Transport class" autoFocus options={options(TRANSPORT_CLASS_LABELS, TRANSPORT_CLASSES)} error={errors.transport_class?.message} {...transportClass} />
        <SelectField
          label="Basis of the classification"
          options={[{ value: '', label: 'Choose' }, ...options(BASIS_LABELS, bases)]}
          error={errors.classification_basis?.message}
          {...register('classification_basis')}
        />
        <TextField label="What the classification rests on" hint={`${REASON_HINT} Required for a professional judgement.`} multiline minRows={2} error={errors.basis_note?.message} {...register('basis_note')} />
        <SelectField label="Packing" options={options(PACKING_LABELS, PACKING_INSTRUCTIONS)} error={errors.packing_instruction?.message} {...register('packing_instruction')} />
        <SelectField label="Coolant" options={[{ value: '', label: 'None' }, ...options(COOLANT_LABELS, COOLANTS)]} error={errors.coolant?.message} {...register('coolant')} />
        <TextField label="Coolant in kg" hint="Required for dry ice: it is marked on the package." autoComplete="off" inputMode="decimal" error={errors.coolant_kg?.message} {...register('coolant_kg')} />
        <TextField label="Responsible person" hint="Answers the phone about the package at all times." autoComplete="off" error={errors.responsible_name?.message} {...register('responsible_name')} />
        <TextField label="Phone of the responsible person" type="tel" autoComplete="off" error={errors.responsible_phone?.message} {...register('responsible_phone')} />
        <TextField label="Carrier" autoComplete="off" error={errors.carrier?.message} {...register('carrier')} />
        <TextField label="Tracking number" autoComplete="off" error={errors.tracking_number?.message} {...register('tracking_number')} />
      </Stack>
    </ConfirmDialog>
  )
}

/**
 * Step 2 (#89): a second person confirms the prepared shipment as it is shown here, the facts
 * that will be recorded, and the vials leave. The server refuses the approver and the
 * preparer, and a preparation other than the one shown.
 */
export function ConfirmShipmentDialog({ labId, request, preparation, open, onClose, onExited, children }: Common & { preparation: Preparation; children: React.ReactNode }) {
  const confirm = useConfirmShipment(labId, request.public_id)
  const [failure, setFailure] = useState<string>()
  const vials = request.lines.reduce((sum, line) => sum + line.reserved.length, 0)
  const run = () => {
    if (confirm.isPending) return
    setFailure(undefined)
    confirm.mutate(
      { preparation: preparation.public_id },
      {
        onSuccess: onClose,
        // A risk group raised since the preparation: the culture is no longer exempt (not_exempt).
        onError: (error) => setFailure(stateError(error) ?? (isApiError(error, 400) ? readProblem(error.body)?.errors?.[0]?.detail : undefined) ?? errorMessage(error)),
      },
    )
  }
  return (
    <ConfirmDialog
      open={open}
      destructive
      title={`Confirm the shipment of request ${request.number}?`}
      description={`${vials === 1 ? 'Its reserved vial leaves' : `All ${vials} reserved vials leave`} the collection today, as prepared by ${preparation.prepared_by}: recorded as distributed and out of their boxes. A shipment cannot be undone. The gates are checked again on today’s date.`}
      confirmLabel="Confirm and ship"
      pending={confirm.isPending}
      error={failure}
      onConfirm={run}
      onClose={onClose}
      onExited={onExited}
    >
      {children}
    </ConfirmDialog>
  )
}

export function WithdrawShipmentDialog({ labId, request, open, onClose, onExited }: Common) {
  const withdraw = useWithdrawShipment(labId, request.public_id)
  return (
    <ReasonDialog
      open={open}
      title={`Withdraw the prepared shipment of request ${request.number}?`}
      description="The request is approved again and its vials stay reserved. The prepared shipment is kept with the reason, and a new one can be prepared."
      confirmLabel="Withdraw the shipment"
      label="Withdrawal"
      pending={withdraw.isPending}
      mutate={(reason, callbacks) => withdraw.mutate({ reason }, callbacks)}
      onClose={onClose}
      onExited={onExited}
    />
  )
}
