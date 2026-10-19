import { zodResolver } from '@hookform/resolvers/zod'
import { useId, useState } from 'react'
import { type FieldValues, type Path, type UseFormSetError, useForm, useWatch } from 'react-hook-form'
import { ConfirmDialog, SelectField, Stack, TextField, Typography } from '@/components/ui'
import { isApiError } from '@/lib/api'
import { applyServerErrors } from '@/lib/forms'
import { usePlace, usePreserve, useRevive, useSetVialStatus, useSubculture } from '../api/mutations'
import {
  type BoxChoice,
  emptyPreserve,
  METHOD_LABELS,
  nextStates,
  type Passage,
  type PlaceForm,
  type PlaceValues,
  placeSchema,
  type PreserveForm,
  type PreserveValues,
  preserveSchema,
  PURPOSE_LABELS,
  rowLabel,
  type StatusForm,
  statusSchema,
  type Vial,
  VIAL_STATUS_LABELS,
} from '../schemas'
import { vialError } from '../vialErrors'

type Common = { labId: string; strainId: string; open: boolean; onClose: () => void; onExited: () => void }

const REASON_HINT = 'Stored for good with the change. Name no person.'
const choose = (label: string) => ({ value: '', label })

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
  return applyServerErrors(error, fields, setError) ? undefined : vialError(error)
}

type PreserveProps = Common & { accession: string; passages: readonly Passage[]; boxes: readonly BoxChoice[] | undefined }

const passageLabel = (p: Passage) => (p.number === 0 ? 'Passage 0, as received' : `Passage ${p.number}`)

export function PreserveBatchDialog({ labId, strainId, accession, passages, boxes, open, onClose, onExited }: PreserveProps) {
  const preserve = usePreserve(labId, strainId)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const latest = passages.at(-1)
  const { register, handleSubmit, formState, setError } = useForm<PreserveForm, unknown, PreserveValues>({
    resolver: zodResolver(preserveSchema),
    defaultValues: emptyPreserve(latest?.public_id),
  })
  const errors = formState.errors
  const onSubmit = handleSubmit((values) => {
    setFailure(undefined)
    preserve.mutate(
      {
        passage: values.passage,
        method: values.method,
        purpose: values.purpose,
        cryoprotectant: values.cryoprotectant.trim(),
        preserved_on: values.preserved_on,
        vial_count: values.vial_count,
        box: values.box || null,
      },
      {
        onSuccess: onClose,
        onError: (error) =>
          setFailure(placeError(error, ['passage', 'method', 'purpose', 'cryoprotectant', 'preserved_on', 'vial_count', 'box'], setError)),
      },
    )
  })
  return (
    <ConfirmDialog
      open={open}
      title={`Preserve a batch of ${accession}`}
      description="A new batch of vials from one passage. With a box, the vials go into its free positions row by row."
      confirmLabel="Preserve batch"
      form={formId}
      pending={preserve.isPending}
      error={failure}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label="New batch" spacing={2} sx={{ mt: 2 }}>
        <SelectField
          label="Passage"
          options={[choose('Choose'), ...passages.toReversed().map((p) => ({ value: p.public_id, label: passageLabel(p) }))]}
          // oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog)
          autoFocus
          error={errors.passage?.message}
          {...register('passage')}
        />
        <SelectField
          label="Method"
          options={Object.entries(METHOD_LABELS).map(([value, label]) => ({ value, label }))}
          error={errors.method?.message}
          {...register('method')}
        />
        <SelectField
          label="Purpose"
          hint="Seed stock is never distributed."
          options={Object.entries(PURPOSE_LABELS).map(([value, label]) => ({ value, label }))}
          error={errors.purpose?.message}
          {...register('purpose')}
        />
        <TextField label="Protectant" hint="For example 10 % glycerol, or skim milk. Optional." autoComplete="off" error={errors.cryoprotectant?.message} {...register('cryoprotectant')} />
        <TextField label="Preserved on" hint="YYYY-MM-DD" autoComplete="off" error={errors.preserved_on?.message} {...register('preserved_on')} />
        <TextField label="Number of vials" hint="1 to 200" inputMode="numeric" autoComplete="off" error={errors.vial_count?.message} {...register('vial_count')} />
        {boxes ? (
          <SelectField
            label="Box"
            hint="Optional. Placed later otherwise."
            options={[choose('Do not place them yet'), ...boxes.map((b) => ({ value: b.public_id, label: b.label }))]}
            error={errors.box?.message}
            {...register('box')}
          />
        ) : (
          <Typography>Loading the boxes…</Typography>
        )}
      </Stack>
    </ConfirmDialog>
  )
}

type VialProps = Common & { vial: Vial }

export function PlaceVialDialog({ labId, strainId, vial, boxes, open, onClose, onExited }: VialProps & { boxes: readonly BoxChoice[] | undefined }) {
  const place = usePlace(labId, strainId)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const current = vial.location
  const { control, register, handleSubmit, formState, setError, setValue } = useForm<PlaceForm, unknown, PlaceValues>({
    resolver: zodResolver(placeSchema),
    defaultValues: { box: current?.box ?? '', row: current ? String(current.row) : '', col: current ? String(current.col) : '' },
  })
  const boxId = useWatch({ control, name: 'box' })
  const box = boxes?.find((b) => b.public_id === boxId)
  const errors = formState.errors
  const rows = Array.from({ length: box?.rows ?? 0 }, (_, i) => ({ value: String(i + 1), label: rowLabel(i + 1) }))
  const cols = Array.from({ length: box?.cols ?? 0 }, (_, i) => ({ value: String(i + 1), label: String(i + 1) }))
  const onSubmit = handleSubmit((values) => {
    setFailure(undefined)
    place.mutate(
      { vialId: vial.public_id, ...values },
      { onSuccess: onClose, onError: (error) => setFailure(placeError(error, ['box', 'row', 'col'], setError)) },
    )
  })
  return (
    <ConfirmDialog
      open={open}
      title={`${vial.placed ? 'Move' : 'Place'} vial ${vial.label}`}
      description="Choose the box and the position. A move keeps the old position in the vial's history."
      confirmLabel={vial.placed ? 'Move vial' : 'Place vial'}
      form={formId}
      pending={place.isPending}
      error={failure}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label="Position" spacing={2} sx={{ mt: 2 }}>
        {boxes ? (
          <>
            <SelectField
              label="Box"
              options={[choose('Choose'), ...boxes.map((b) => ({ value: b.public_id, label: b.label }))]}
              // oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog)
              autoFocus
              error={errors.box?.message}
              {...register('box', {
                // Another box has other rows and columns: the position is chosen again.
                onChange: () => {
                  setValue('row', '')
                  setValue('col', '')
                },
              })}
            />
            <Stack direction="row" spacing={2}>
              <SelectField label="Row" options={[choose(box ? 'Choose' : 'Box first'), ...rows]} error={errors.row?.message} {...register('row')} />
              <SelectField label="Column" options={[choose(box ? 'Choose' : 'Box first'), ...cols]} error={errors.col?.message} {...register('col')} />
            </Stack>
          </>
        ) : (
          <Typography>Loading the boxes…</Typography>
        )}
      </Stack>
    </ConfirmDialog>
  )
}

export function VialStatusDialog({ labId, strainId, vial, open, onClose, onExited }: VialProps) {
  const change = useSetVialStatus(labId, strainId)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const states = nextStates(vial)
  const { register, handleSubmit, formState, setError } = useForm<StatusForm>({
    resolver: zodResolver(statusSchema),
    defaultValues: { status: states[0] ?? 'available', reason: '' },
  })
  const onSubmit = handleSubmit((values) => {
    setFailure(undefined)
    change.mutate(
      { vialId: vial.public_id, status: values.status, reason: values.reason.trim() },
      {
        onSuccess: onClose,
        onError: (error) =>
          setFailure(placeError(error, ['status', 'reason'], setError, () => setError('reason', { type: 'server', message: 'Say why' }, { shouldFocus: true }))),
      },
    )
  })
  return (
    <ConfirmDialog
      open={open}
      title={`Change the state of vial ${vial.label}`}
      description={`Now ${VIAL_STATUS_LABELS[vial.status].toLowerCase()}. A vial that is consumed, destroyed, lost or entered in error leaves its position.`}
      confirmLabel="Save state"
      form={formId}
      pending={change.isPending}
      error={failure}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label="New state" spacing={2} sx={{ mt: 2 }}>
        <SelectField
          label="New state"
          options={states.map((value) => ({ value, label: VIAL_STATUS_LABELS[value] }))}
          // oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog)
          autoFocus
          error={formState.errors.status?.message}
          {...register('status')}
        />
        <TextField label="Reason" hint={REASON_HINT} multiline minRows={2} error={formState.errors.reason?.message} {...register('reason')} />
      </Stack>
    </ConfirmDialog>
  )
}

export function ReviveDialog({ labId, strainId, vial, open, onClose, onExited }: VialProps) {
  const revive = useRevive(labId, strainId)
  const [failure, setFailure] = useState<string>()
  return (
    <ConfirmDialog
      open={open}
      title={`Revive vial ${vial.label}?`}
      description="The vial is used up and leaves its position, and a new passage starts from it. This cannot be undone."
      confirmLabel="Revive vial"
      destructive
      pending={revive.isPending}
      error={failure}
      onConfirm={() => {
        setFailure(undefined)
        revive.mutate(vial.public_id, { onSuccess: onClose, onError: (error) => setFailure(vialError(error)) })
      }}
      onClose={onClose}
      onExited={onExited}
    />
  )
}

export function SubcultureDialog({ labId, strainId, passage, open, onClose, onExited }: Common & { passage: Passage }) {
  const subculture = useSubculture(labId, strainId)
  const [failure, setFailure] = useState<string>()
  return (
    <ConfirmDialog
      open={open}
      title={`Subculture passage ${passage.number}`}
      description={`Records passage ${passage.number + 1}, grown from passage ${passage.number}.`}
      confirmLabel="Record subculture"
      pending={subculture.isPending}
      error={failure}
      onConfirm={() => {
        setFailure(undefined)
        subculture.mutate(passage.public_id, { onSuccess: onClose, onError: (error) => setFailure(vialError(error)) })
      }}
      onClose={onClose}
      onExited={onExited}
    />
  )
}
