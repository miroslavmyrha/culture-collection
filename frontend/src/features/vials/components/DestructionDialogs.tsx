import { zodResolver } from '@hookform/resolvers/zod'
import { useId, useState } from 'react'
import { type FieldValues, type Path, type UseFormSetError, useForm, useWatch } from 'react-hook-form'
import { CheckboxField, ConfirmDialog, Stack, TextField, Typography } from '@/components/ui'
import { isApiError } from '@/lib/api'
import { applyServerErrors } from '@/lib/forms'
import { useConfirmDestruction, useDestructionInError, useRecordDestruction } from '../api/mutations'
import { useVialsToDestroy, useWitnesses } from '../api/queries'
import {
  type DecisionForm,
  decisionSchema,
  type Destruction,
  DESTRUCTION_METHOD_LABELS,
  type DestructionForm,
  type DestructionRules,
  type DestructionValues,
  destructionSchema,
  emptyDestruction,
} from '../schemas'
import { vialError } from '../vialErrors'
import { MethodFields, OutsideFields, VialsFieldset, WitnessField } from './DestructionFormGroups'

type Common = { labId: string; strainId: string; open: boolean; onClose: () => void; onExited: () => void }

const REASON_HINT = 'Stored for good with the record. Name no person.'

/** Field errors on their fields (the first focused); anything else is the dialog's message. */
function failureOf<T extends FieldValues>(error: unknown, fields: readonly Path<T>[], setError: UseFormSetError<T>, reasonField?: Path<T>): string | undefined {
  if (reasonField && isApiError(error) && error.code === 'reason_required') {
    setError(reasonField, { type: 'server', message: 'Say why' }, { shouldFocus: true })
    return undefined
  }
  return applyServerErrors(error, fields, setError) ? undefined : vialError(error)
}

const DESTRUCTION_FIELDS = [
  'vials',
  'destroyed_on',
  'method',
  'method_detail',
  'verification',
  'contractor',
  'handover_document',
  'inactivated_in_lab',
  'run',
  'witness',
  'reason',
] as const

type RecordProps = Common & {
  rules: DestructionRules
  /** Vials in a record that waits for its confirmation: no second record takes them. */
  waiting: ReadonlySet<string>
}

/** The vials the form is built from, with whether more wait than the list holds. Undefined while there is nothing to record. */
function readyVials<V>(data: { count: number; results: readonly unknown[] } | undefined, free: V[] | undefined) {
  if (data === undefined || free === undefined || free.length === 0) return undefined
  return { free, more: data.count > data.results.length }
}

/** Why there is no form: the vials are loading, failed to load, or none is left to record. */
function noticeOf(vials: { data: unknown; isError: boolean }): string {
  if (vials.data !== undefined) return 'No vial of this strain is marked to destroy outside a record that waits for its confirmation.'
  return vials.isError ? 'The vials to destroy could not be loaded. Close this and try again.' : 'Loading the vials to destroy…'
}

/**
 * Records the destruction of the strain's vials marked to destroy (#160). Its fields follow the
 * strain's restriction kinds (destructionRules): a regulated strain says how the inactivation was
 * verified and waits for a manager's confirmation, a VRAT names its witness. The vials load with
 * the dialog, and the form mounts once they are there, every one of them chosen.
 */
export function RecordDestructionDialog({ labId, strainId, rules, waiting, open, onClose, onExited }: RecordProps) {
  const vials = useVialsToDestroy(labId, strainId)
  const free = vials.data?.results.filter((v) => !waiting.has(v.public_id))
  const formId = useId()
  const record = useRecordDestruction(labId, strainId)
  const [failure, setFailure] = useState<string>()
  // Nothing to record: the button only closes the dialog.
  const ready = readyVials(vials.data, free)
  const action = ready ? { form: formId } : { onConfirm: onClose }
  return (
    <ConfirmDialog
      open={open}
      title="Record a destruction"
      description={
        rules.confirmation
          ? 'The strain is regulated: a manager other than you confirms this record, and its vials are destroyed then (ADR 0009).'
          : 'The strain has no active restriction: its vials are destroyed and leave their boxes when you record this.'
      }
      confirmLabel={rules.confirmation ? 'Record for confirmation' : 'Record and destroy'}
      {...action}
      pending={record.isPending}
      error={failure}
      onClose={onClose}
      onExited={onExited}
    >
      {ready === undefined ? (
        <Typography sx={{ mt: 2 }}>{noticeOf(vials)}</Typography>
      ) : (
        <DestructionFields
          formId={formId}
          labId={labId}
          rules={rules}
          vials={ready.free}
          more={ready.more}
          onSubmit={(values, setError) => {
            setFailure(undefined)
            record.mutate(
              {
                strain: strainId,
                vials: values.vials,
                destroyed_on: values.destroyed_on,
                method: values.method,
                method_detail: values.method_detail,
                verification: values.verification,
                contractor: values.outside ? values.contractor : '',
                handover_document: values.outside ? values.handover_document : '',
                inactivated_in_lab: values.outside ? values.inactivated_in_lab : true,
                run: values.run,
                witness: values.witness === '' ? null : values.witness,
                reason: values.reason,
              },
              { onSuccess: onClose, onError: (error) => setFailure(failureOf(error, DESTRUCTION_FIELDS, setError, 'reason')) },
            )
          }}
        />
      )}
    </ConfirmDialog>
  )
}

type FieldsProps = {
  formId: string
  labId: string
  rules: DestructionRules
  vials: readonly { public_id: string; label: string }[]
  /** The strain has more vials to destroy than one answer lists. */
  more: boolean
  onSubmit: (values: DestructionValues, setError: UseFormSetError<DestructionForm>) => void
}

function DestructionFields({ formId, labId, rules, vials, more, onSubmit }: FieldsProps) {
  const witnesses = useWitnesses(labId, rules.witness)
  const { control, register, handleSubmit, formState, setError } = useForm<DestructionForm, unknown, DestructionValues>({
    resolver: zodResolver(destructionSchema(rules)),
    defaultValues: { ...emptyDestruction(), vials: vials.map((v) => v.public_id) },
  })
  const errors = formState.errors
  const outside = useWatch({ control, name: 'outside' })
  const group = { register, errors }
  return (
    <Stack component="form" id={formId} onSubmit={handleSubmit((values) => onSubmit(values, setError))} noValidate aria-label="Destruction" spacing={2} sx={{ mt: 2 }}>
      <VialsFieldset vials={vials} more={more} {...group} />
      <TextField label="Destroyed on" hint="YYYY-MM-DD" autoComplete="off" error={errors.destroyed_on?.message} {...register('destroyed_on')} />
      <MethodFields rules={rules} {...group} />
      {rules.witness && <WitnessField witnesses={witnesses} {...group} />}
      <CheckboxField label="Handed to an outside firm" {...register('outside')} />
      {outside && <OutsideFields {...group} />}
      <TextField label="Run" hint="Optional. The autoclave cycle or run, as the lab names it." autoComplete="off" error={errors.run?.message} {...register('run')} />
      <TextField label="Reason" hint={REASON_HINT} multiline minRows={2} error={errors.reason?.message} {...register('reason')} />
    </Stack>
  )
}

type RecordRowProps = Common & { record: Destruction; accession: string }

const vialsText = (d: Destruction) => `${d.vials.length} ${d.vials.length === 1 ? 'vial' : 'vials'}`

/**
 * A manager other than the recorder confirms a regulated strain's destruction (ADR 0009): its
 * vials are destroyed now and leave their boxes. The server refuses the recorder.
 */
export function ConfirmDestructionDialog({ labId, strainId, record, accession, open, onClose, onExited }: RecordRowProps) {
  const confirm = useConfirmDestruction(labId, strainId)
  const [failure, setFailure] = useState<string>()
  return (
    <ConfirmDialog
      open={open}
      title={`Confirm destruction ${record.number}?`}
      description={`${vialsText(record)} of ${accession}, destroyed on ${record.destroyed_on} by ${DESTRUCTION_METHOD_LABELS[record.method].toLowerCase()}, recorded by ${record.recorded_by}${record.witness ? ` with ${record.witness} as witness` : ''}. Confirmed, the vials are destroyed and leave their boxes. This cannot be undone.`}
      confirmLabel="Confirm destruction"
      destructive
      pending={confirm.isPending}
      error={failure}
      onConfirm={() => {
        setFailure(undefined)
        confirm.mutate(record.public_id, { onSuccess: onClose, onError: (error) => setFailure(vialError(error)) })
      }}
      onClose={onClose}
      onExited={onExited}
    />
  )
}

/** A wrong record stays in the history, marked, with the reason (decree 474/2002 Sb., § 5(4)). */
export function DestructionErrorDialog({ labId, strainId, record, open, onClose, onExited }: RecordRowProps) {
  const enter = useDestructionInError(labId, strainId)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const { register, handleSubmit, formState, setError } = useForm<DecisionForm>({ resolver: zodResolver(decisionSchema), defaultValues: { reason: '' } })
  const onSubmit = handleSubmit((values) => {
    setFailure(undefined)
    enter.mutate(
      { recordId: record.public_id, reason: values.reason.trim() },
      { onSuccess: onClose, onError: (error) => setFailure(failureOf(error, ['reason'], setError, 'reason')) },
    )
  })
  return (
    <ConfirmDialog
      open={open}
      title={`Enter destruction ${record.number} in error?`}
      description={
        record.completed_at === null
          ? 'It stays in the history, marked. Its vials stay marked to destroy, for a new record. This cannot be undone.'
          : 'It stays in the history, marked. Its vials stay destroyed: the material is gone. This cannot be undone.'
      }
      confirmLabel="Enter in error"
      destructive
      form={formId}
      pending={enter.isPending}
      error={failure}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label="Entered in error" spacing={2} sx={{ mt: 2 }}>
        <TextField label="Reason" hint={REASON_HINT} multiline minRows={2} error={formState.errors.reason?.message} {...register('reason')} />
      </Stack>
    </ConfirmDialog>
  )
}
