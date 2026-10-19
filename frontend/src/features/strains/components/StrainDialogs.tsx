import { zodResolver } from '@hookform/resolvers/zod'
import { useId, useState } from 'react'
import { type FieldValues, type Path, type UseFormSetError, useController, useForm, useWatch } from 'react-hook-form'
import { ConfirmDialog, SelectField, Stack, TextField } from '@/components/ui'
import { isApiError } from '@/lib/api'
import { applyServerErrors } from '@/lib/forms'
import { useAddRestriction, useEndRestriction, useReclassify, useSetRiskGroup } from '../api/mutations'
import {
  type AddRestrictionForm,
  addRestrictionSchema,
  emptyRestriction,
  type EndRestrictionForm,
  endRestrictionSchema,
  GMO_CATEGORIES,
  GMO_CATEGORY_LABELS,
  options,
  REFERENCE_HINTS,
  RESTRICTION_KINDS,
  RESTRICTION_LABELS,
  type ReclassifyForm,
  reclassifySchema,
  restrictionBody,
  type RiskGroupForm,
  riskGroupSchema,
  type RiskGroupValues,
  type Strain,
} from '../schemas'
import { PERMIT_REFUSED_BY_KIND, RISK_GROUP_4_REFUSED, strainError } from '../strainErrors'
import { TaxonField } from './TaxonField'

type Common = { labId: string; strain: Strain; open: boolean; onClose: () => void; onExited: () => void }

const REASON_HINT = 'Stored for good with the change. Name no person.'
const KIND_OPTIONS = options(RESTRICTION_LABELS, RESTRICTION_KINDS)
const CATEGORY_OPTIONS = [{ value: '', label: 'Choose' }, ...GMO_CATEGORIES.map((value) => ({ value: String(value), label: GMO_CATEGORY_LABELS[value] ?? '' }))]
const RISK_OPTIONS = ['1', '2', '3', '4'].map((value) => ({ value, label: value }))
const today = () => new Date().toLocaleDateString('sv')

/**
 * The failure of a dialog's request: field errors on their fields (focused), everything else
 * as the dialog's own message. Returns that message, or undefined when a field took it.
 */
function placeError<T extends FieldValues>(
  error: unknown,
  fields: readonly Path<T>[],
  setError: UseFormSetError<T>,
  onReasonMissing?: () => void,
): string | undefined {
  if (isApiError(error) && error.code === 'reason_required' && onReasonMissing) {
    onReasonMissing()
    return undefined
  }
  return applyServerErrors(error, fields, setError) ? undefined : strainError(error)
}

const missing = { type: 'server', message: 'Say why' } as const

export function ReclassifyDialog({ labId, strain, open, onClose, onExited }: Common) {
  const reclassify = useReclassify(labId, strain.public_id)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const { control, register, handleSubmit, formState, setError } = useForm<ReclassifyForm>({
    resolver: zodResolver(reclassifySchema),
    defaultValues: { taxon: null, identified_on: today(), method: '', reason: '' },
  })
  const errors = formState.errors
  // Registered before the fields below, so a missing taxon is the one focused first.
  const { field: taxonController } = useController({ control, name: 'taxon' })
  const { value: taxon, onChange: onTaxonChange, onBlur: onTaxonBlur, ref: taxonRef } = taxonController
  const onSubmit = handleSubmit((values) => {
    if (!values.taxon) return
    setFailure(undefined)
    reclassify.mutate(
      { taxon: values.taxon.public_id, identified_on: values.identified_on, method: values.method.trim(), reason: values.reason.trim() },
      { onSuccess: onClose, onError: (error) => setFailure(placeError(error, ['taxon', 'identified_on', 'method', 'reason'], setError, () => setError('reason', missing, { shouldFocus: true }))) },
    )
  })
  return (
    <ConfirmDialog
      open={open}
      title={`Reclassify ${strain.accession_number ?? 'the strain'}`}
      description="The new identification becomes the current one. The earlier ones stay in the history."
      confirmLabel="Save identification"
      form={formId}
      pending={reclassify.isPending}
      error={failure}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label="New identification" spacing={2} sx={{ mt: 2 }}>
        {/* oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog) */}
        <TaxonField label="Taxon" autoFocus error={errors.taxon?.message} value={taxon ?? null} onChange={onTaxonChange} onBlur={onTaxonBlur} ref={taxonRef} />
        <TextField label="Identified on" hint="YYYY-MM-DD" autoComplete="off" error={errors.identified_on?.message} {...register('identified_on')} />
        <TextField label="Method" hint="For example 16S rRNA gene sequence. Name no person." autoComplete="off" error={errors.method?.message} {...register('method')} />
        <TextField label="Reason" hint={REASON_HINT} multiline minRows={2} error={errors.reason?.message} {...register('reason')} />
      </Stack>
    </ConfirmDialog>
  )
}

export function RiskGroupDialog({ labId, strain, open, onClose, onExited }: Common) {
  const change = useSetRiskGroup(labId, strain.public_id)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const { register, handleSubmit, formState, setError } = useForm<RiskGroupForm, unknown, RiskGroupValues>({
    resolver: zodResolver(riskGroupSchema),
    defaultValues: { risk_group: String(strain.risk_group), reason: '' },
  })
  const onSubmit = handleSubmit((values) => {
    setFailure(undefined)
    change.mutate(values, {
      onSuccess: onClose,
      onError: (error) => {
        if (isApiError(error) && error.code === 'risk_group_4_refused') {
          setError('risk_group', { type: 'server', message: RISK_GROUP_4_REFUSED }, { shouldFocus: true })
          return
        }
        setFailure(placeError(error, ['risk_group', 'reason'], setError, () => setError('reason', missing, { shouldFocus: true })))
      },
    })
  })
  return (
    <ConfirmDialog
      open={open}
      title={`Change the risk group of ${strain.accession_number ?? 'the strain'}`}
      description="Only with a reason. The change and the reason go into the strain's history."
      confirmLabel="Save risk group"
      form={formId}
      pending={change.isPending}
      error={failure}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label="Risk group" spacing={2} sx={{ mt: 2 }}>
        {/* oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog) */}
        <SelectField label="Risk group" options={RISK_OPTIONS} autoFocus error={formState.errors.risk_group?.message} {...register('risk_group')} />
        <TextField label="Reason" hint={REASON_HINT} multiline minRows={2} error={formState.errors.reason?.message} {...register('reason')} />
      </Stack>
    </ConfirmDialog>
  )
}

export function AddRestrictionDialog({ labId, strain, open, onClose, onExited }: Common) {
  const add = useAddRestriction(labId, strain.public_id)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const { control, register, handleSubmit, formState, setError } = useForm<AddRestrictionForm>({
    resolver: zodResolver(addRestrictionSchema),
    defaultValues: { ...emptyRestriction, reason: '' },
  })
  const kind = useWatch({ control, name: 'kind' })
  const errors = formState.errors
  const onSubmit = handleSubmit((values) => {
    setFailure(undefined)
    add.mutate(
      { ...restrictionBody(values), reason: values.reason.trim() },
      {
        onSuccess: onClose,
        onError: (error) => {
          if (isApiError(error, 422) && error.code === 'lab_authorisation_required') {
            setError('kind', { type: 'server', message: PERMIT_REFUSED_BY_KIND[values.kind] ?? strainError(error) }, { shouldFocus: true })
            return
          }
          setFailure(placeError(error, ['kind', 'reference', 'act', 'gmo_category', 'reason'], setError, () => setError('reason', missing, { shouldFocus: true })))
        },
      },
    )
  })
  return (
    <ConfirmDialog
      open={open}
      title={`Add a restriction to ${strain.accession_number ?? 'the strain'}`}
      description="A regulatory list the agent is on. A VRAT or a quarantine pest needs the lab's permit."
      confirmLabel="Add restriction"
      form={formId}
      pending={add.isPending}
      error={failure}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label="Restriction" spacing={2} sx={{ mt: 2 }}>
        {/* oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog) */}
        <SelectField label="Kind" options={KIND_OPTIONS} autoFocus error={errors.kind?.message} {...register('kind')} />
        <TextField label="List entry" hint={REFERENCE_HINTS[kind]} autoComplete="off" error={errors.reference?.message} {...register('reference')} />
        {kind === 'dual_use' && (
          <TextField
            label="Act Annex I was read in"
            hint="For example (EU) 2025/2003"
            autoComplete="off"
            error={errors.act?.message}
            {...register('act')}
          />
        )}
        {kind === 'gmo' && (
          <SelectField label="Contained use category" options={CATEGORY_OPTIONS} error={errors.gmo_category?.message} {...register('gmo_category')} />
        )}
        <TextField label="Reason" hint={REASON_HINT} multiline minRows={2} error={errors.reason?.message} {...register('reason')} />
      </Stack>
    </ConfirmDialog>
  )
}

type EndProps = Common & { restriction: Strain['restriction_history'][number] }

export function EndRestrictionDialog({ labId, strain, restriction, open, onClose, onExited }: EndProps) {
  const end = useEndRestriction(labId, strain.public_id)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const { register, handleSubmit, formState, setError } = useForm<EndRestrictionForm>({
    resolver: zodResolver(endRestrictionSchema),
    defaultValues: { reason: '' },
  })
  const onSubmit = handleSubmit((values) => {
    setFailure(undefined)
    end.mutate(
      { restrictionId: restriction.public_id, reason: values.reason.trim() },
      { onSuccess: onClose, onError: (error) => setFailure(placeError(error, ['reason'], setError, () => setError('reason', missing, { shouldFocus: true }))) },
    )
  })
  return (
    <ConfirmDialog
      open={open}
      title={`End the restriction ${restriction.reference}`}
      description={`${RESTRICTION_LABELS[restriction.kind]}: it stays in the history with the time it ended and the reason.`}
      confirmLabel="End restriction"
      form={formId}
      pending={end.isPending}
      error={failure}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label="End the restriction" spacing={2} sx={{ mt: 2 }}>
        {/* oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog) */}
        <TextField label="Reason" hint={REASON_HINT} multiline minRows={2} autoFocus error={formState.errors.reason?.message} {...register('reason')} />
      </Stack>
    </ConfirmDialog>
  )
}
