import { zodResolver } from '@hookform/resolvers/zod'
import { useId, useState } from 'react'
import { type FieldValues, type Path, type UseFormSetError, useForm, useWatch } from 'react-hook-form'
import { ConfirmDialog, SelectField, Stack, TextField, Typography } from '@/components/ui'
import { isApiError } from '@/lib/api'
import { applyServerErrors } from '@/lib/forms'
import { useDecideBatch, useEnterCheckInError, useRecordCheck } from '../api/mutations'
import {
  type Batch,
  type BatchCheck,
  CHECK_KINDS,
  CHECK_METHOD_LABELS,
  type CheckForm,
  type CheckValues,
  checkSchema,
  type DecisionForm,
  decisionSchema,
  emptyCheck,
  KIND_LABELS,
  kindsText,
  METHODS_BY_KIND,
  notPassed,
  RESULT_LABELS,
  STAGE_LABELS,
  UNIT_LABELS,
  type Vial,
} from '../schemas'
import { vialError } from '../vialErrors'

type Common = { labId: string; strainId: string; open: boolean; onClose: () => void; onExited: () => void }

const REASON_HINT = 'Stored for good with the change. Name no person.'

/** Field errors on their fields (the first focused); anything else is the dialog's message. */
function failureOf<T extends FieldValues>(error: unknown, fields: readonly Path<T>[], setError: UseFormSetError<T>, reasonField?: Path<T>): string | undefined {
  if (reasonField && isApiError(error) && error.code === 'reason_required') {
    setError(reasonField, { type: 'server', message: 'Say why' }, { shouldFocus: true })
    return undefined
  }
  return applyServerErrors(error, fields, setError) ? undefined : vialError(error)
}

const CHECK_FIELDS = ['kind', 'stage', 'checked_on', 'method', 'method_detail', 'result', 'value', 'unit', 'vial', 'note'] as const

type RecordProps = Common & {
  batch: Batch
  /** The batch's vials, undefined while they load: its available ones may be checked. */
  vials: readonly Vial[] | undefined
  /** The batch's checks when loaded: a vial an earlier check used may serve again. */
  checks: readonly BatchCheck[] | undefined
}

/** Records one check of a batch (technicians and up). The vial named is used up by the check. */
export function RecordCheckDialog({ labId, strainId, batch, vials, checks, open, onClose, onExited }: RecordProps) {
  const record = useRecordCheck(labId, strainId)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const { control, register, handleSubmit, formState, setError, setValue } = useForm<CheckForm, unknown, CheckValues>({
    resolver: zodResolver(checkSchema),
    defaultValues: emptyCheck(batch),
  })
  const kind = useWatch({ control, name: 'kind' })
  const errors = formState.errors
  const available = (vials ?? []).filter((v) => v.batch === batch.public_id && v.status === 'available')
  const used = new Map((checks ?? []).flatMap((c) => (c.vial && c.vial_label ? [[c.vial, c.vial_label] as const] : [])))
  const vialOptions = [
    { value: '', label: 'None named' },
    ...available.map((v) => ({ value: v.public_id, label: v.label })),
    ...[...used].map(([id, label]) => ({ value: id, label: `${label}, used by an earlier check` })),
  ]
  const missing = notPassed(batch)
  const onSubmit = handleSubmit((values) => {
    setFailure(undefined)
    record.mutate(
      {
        batch: batch.public_id,
        kind: values.kind,
        stage: values.stage,
        checked_on: values.checked_on,
        method: values.method,
        method_detail: values.method_detail,
        result: values.result,
        value: values.value === '' ? null : values.value,
        unit: values.unit === '' ? null : values.unit,
        vial: values.vial === '' ? null : values.vial,
        note: values.note,
        reason: '',
      },
      { onSuccess: onClose, onError: (error) => setFailure(failureOf(error, CHECK_FIELDS, setError)) },
    )
  })
  return (
    <ConfirmDialog
      open={open}
      title={`Record a check of batch ${batch.number}`}
      description={
        missing.length > 0
          ? `It waits for a passed ${kindsText(missing)} check. A vial named here is used up by the check.`
          : 'Its latest checks passed. A vial named here is used up by the check.'
      }
      confirmLabel="Record check"
      form={formId}
      pending={record.isPending}
      error={failure}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label="New check" spacing={2} sx={{ mt: 2 }}>
        <SelectField
          label="Kind"
          options={CHECK_KINDS.map((value) => ({ value, label: KIND_LABELS[value] }))}
          // oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog)
          autoFocus
          error={errors.kind?.message}
          {...register('kind', {
            // Each kind has its own methods: the first one of the new kind is chosen.
            onChange: (event: { target: { value: string } }) => {
              const next = CHECK_KINDS.find((k) => k === event.target.value)
              if (next) setValue('method', METHODS_BY_KIND[next][0] ?? 'other')
            },
          })}
        />
        <SelectField
          label="Stage"
          options={Object.entries(STAGE_LABELS).map(([value, label]) => ({ value, label }))}
          error={errors.stage?.message}
          {...register('stage')}
        />
        <TextField label="Checked on" hint="YYYY-MM-DD" autoComplete="off" error={errors.checked_on?.message} {...register('checked_on')} />
        <SelectField
          // A new kind brings other options: mounted again, it shows the method the kind set.
          key={kind}
          label="Method"
          options={METHODS_BY_KIND[kind].map((value) => ({ value, label: CHECK_METHOD_LABELS[value] }))}
          error={errors.method?.message}
          {...register('method')}
        />
        <TextField
          label="Method details"
          hint="Medium, temperature, gene. Required for Other."
          autoComplete="off"
          error={errors.method_detail?.message}
          {...register('method_detail')}
        />
        <SelectField
          label="Result"
          hint="Reduced counts as passed for a release. Say in the note what was seen."
          options={Object.entries(RESULT_LABELS).map(([value, label]) => ({ value, label }))}
          error={errors.result?.message}
          {...register('result')}
        />
        <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap' }}>
          <TextField label="Value" hint="Optional, as 2.1e8" inputMode="decimal" autoComplete="off" error={errors.value?.message} {...register('value')} />
          <SelectField
            label="Unit"
            options={[{ value: '', label: 'None' }, ...Object.entries(UNIT_LABELS).map(([value, label]) => ({ value, label }))]}
            error={errors.unit?.message}
            {...register('unit')}
          />
        </Stack>
        {/* Mounted once its options are there, so a chosen vial is never lost to a late list. */}
        {vials === undefined ? (
          <Typography>Loading the vials of the batch…</Typography>
        ) : (
          <SelectField label="Vial checked" hint="Optional. Used up by the check." options={vialOptions} error={errors.vial?.message} {...register('vial')} />
        )}
        <TextField label="Note" hint="What was seen. Required for a reduced result. Name no person." multiline minRows={2} error={errors.note?.message} {...register('note')} />
      </Stack>
    </ConfirmDialog>
  )
}

type DecisionProps = Common & { batch: Batch; decision: 'release' | 'hold' }

/** A curator releases a batch after its checks passed, or holds it, with a reason. */
export function BatchDecisionDialog({ labId, strainId, batch, decision, open, onClose, onExited }: DecisionProps) {
  const decide = useDecideBatch(labId, strainId)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const { register, handleSubmit, formState, setError } = useForm<DecisionForm>({ resolver: zodResolver(decisionSchema), defaultValues: { reason: '' } })
  const release = decision === 'release'
  const onSubmit = handleSubmit((values) => {
    setFailure(undefined)
    decide.mutate(
      { batchId: batch.public_id, decision, reason: values.reason.trim() },
      { onSuccess: onClose, onError: (error) => setFailure(failureOf(error, ['reason'], setError, 'reason')) },
    )
  })
  return (
    <ConfirmDialog
      open={open}
      title={`${release ? 'Release' : 'Hold'} batch ${batch.number}`}
      description={
        release
          ? 'Its latest identity, purity and viability checks passed. Released, its distribution vials may be sent.'
          : 'Nothing of a held batch is sent until a curator releases it again.'
      }
      confirmLabel={release ? 'Release batch' : 'Hold batch'}
      form={formId}
      pending={decide.isPending}
      error={failure}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label={release ? 'Release' : 'Hold'} spacing={2} sx={{ mt: 2 }}>
        <TextField
          label="Reason"
          hint={REASON_HINT}
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

type ErrorProps = Common & { check: BatchCheck }

/** A wrong check leaves the release rule; the row stays, marked, with the reason. */
export function CheckErrorDialog({ labId, strainId, check, open, onClose, onExited }: ErrorProps) {
  const enter = useEnterCheckInError(labId, strainId)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const { register, handleSubmit, formState, setError } = useForm<DecisionForm>({ resolver: zodResolver(decisionSchema), defaultValues: { reason: '' } })
  const onSubmit = handleSubmit((values) => {
    setFailure(undefined)
    enter.mutate(
      { checkId: check.public_id, reason: values.reason.trim() },
      { onSuccess: onClose, onError: (error) => setFailure(failureOf(error, ['reason'], setError, 'reason')) },
    )
  })
  const what = `${KIND_LABELS[check.kind].toLowerCase()} check of ${check.checked_on}`
  return (
    <ConfirmDialog
      open={open}
      title={`Enter the ${what} in error?`}
      description="It stays in the history, marked, and no longer counts for a release. A released batch that loses a passed check waits for its checks again. This cannot be undone."
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
