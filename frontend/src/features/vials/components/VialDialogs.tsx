import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { type FieldValues, type Path, type UseFormSetError, useForm, useWatch } from 'react-hook-form'
import { GrowthFields } from '@/components/GrowthFields'
import { ConfirmDialog, SelectField, Stack, TextField, Typography } from '@/components/ui'
import { isApiError } from '@/lib/api'
import { applyServerErrors } from '@/lib/forms'
import { type Growth, type GrowthBody, type GrowthForm, GROWTH_FIELDS, growthBody, growthDefaults, growthSchema, mediaListOptions } from '@/lib/growth'
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
// A failed box load is no empty list: "no boxes" would read as a lab without storage.
const BOXES_FAILED = 'Could not load the boxes. Close this dialog and try again.'
const BOXES_FAILED_PRESERVE = 'Could not load the boxes, so the vials cannot be placed now. Close this dialog and try again, or preserve them and place them later.'
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

type PreserveProps = Common & { accession: string; passages: readonly Passage[]; boxes: readonly BoxChoice[] | undefined; boxesFailed?: boolean }

const passageLabel = (p: Passage) => (p.number === 0 ? 'Passage 0, as received' : `Passage ${p.number}`)

export function PreserveBatchDialog({ labId, strainId, accession, passages, boxes, boxesFailed, open, onClose, onExited }: PreserveProps) {
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
      error={failure ?? (boxesFailed ? BOXES_FAILED_PRESERVE : undefined)}
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
          !boxesFailed && <Typography>Loading the boxes…</Typography>
        )}
      </Stack>
    </ConfirmDialog>
  )
}

type VialProps = Common & { vial: Vial }

type PlaceProps = VialProps & {
  boxes: readonly BoxChoice[] | undefined
  boxesFailed?: boolean
  /** After the server placed or moved the vial, before the dialog closes. */
  onPlaced?: () => void
}

export function PlaceVialDialog({ labId, strainId, vial, boxes, boxesFailed, open, onClose, onExited, onPlaced }: PlaceProps) {
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
      {
        onSuccess: () => {
          onPlaced?.()
          onClose()
        },
        onError: (error) => setFailure(placeError(error, ['box', 'row', 'col'], setError)),
      },
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
      error={failure ?? (boxesFailed ? BOXES_FAILED : undefined)}
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
          !boxesFailed && <Typography>Loading the boxes…</Typography>
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

type StepProps = Common & {
  /** The strain's own conditions: what the new passage records unless the person changes them. */
  strainGrowth: Growth
  title: string
  description: string
  confirmLabel: string
  label: string
  destructive?: boolean
  pending: boolean
  send: (growth: GrowthBody | undefined, options: { onSuccess: () => void; onError: (error: unknown) => void }) => void
}

/**
 * A revival or a subculture starts a passage (#79). It records the medium, temperature and
 * atmosphere it used: the fields start as the strain's. Left as they are, nothing is sent and
 * the server records the strain's; changed, the conditions of this passage are sent whole.
 */
function GrowthStepDialog({ labId, strainGrowth, title, description, confirmLabel, label, destructive, pending, send, open, onClose, onExited }: StepProps) {
  const media = useQuery(mediaListOptions(labId))
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const { register, handleSubmit, formState, setError } = useForm<GrowthForm>({ resolver: zodResolver(growthSchema), defaultValues: growthDefaults(strainGrowth) })
  const onSubmit = handleSubmit((values) => {
    setFailure(undefined)
    const body = growthBody(values)
    const unchanged = JSON.stringify(body) === JSON.stringify(growthBody(growthDefaults(strainGrowth)))
    send(unchanged ? undefined : body, { onSuccess: onClose, onError: (error) => setFailure(placeError(error, GROWTH_FIELDS, setError)) })
  })
  return (
    <ConfirmDialog
      open={open}
      title={title}
      description={description}
      confirmLabel={confirmLabel}
      destructive={destructive ?? false}
      form={formId}
      pending={pending}
      error={failure}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label={label} spacing={2} sx={{ mt: 2 }}>
        {/* oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog) */}
        <GrowthFields register={(name) => register(name)} errors={formState.errors} media={media.data?.results} mediaFailed={media.isError && media.data === undefined} current={strainGrowth.medium} autoFocus={!destructive} />
      </Stack>
    </ConfirmDialog>
  )
}

export function ReviveDialog({ labId, strainId, vial, strainGrowth, open, onClose, onExited }: VialProps & { strainGrowth: Growth }) {
  const revive = useRevive(labId, strainId)
  return (
    <GrowthStepDialog
      labId={labId}
      strainId={strainId}
      strainGrowth={strainGrowth}
      title={`Revive vial ${vial.label}?`}
      description="The vial is used up and leaves its position, and a new passage starts from it. This cannot be undone. Record how the culture is grown."
      confirmLabel="Revive vial"
      label="Growth conditions of the revival"
      destructive
      pending={revive.isPending}
      send={(growth, options) => revive.mutate({ vialId: vial.public_id, growth }, options)}
      open={open}
      onClose={onClose}
      onExited={onExited}
    />
  )
}

export function SubcultureDialog({ labId, strainId, passage, strainGrowth, open, onClose, onExited }: Common & { passage: Passage; strainGrowth: Growth }) {
  const subculture = useSubculture(labId, strainId)
  return (
    <GrowthStepDialog
      labId={labId}
      strainId={strainId}
      strainGrowth={strainGrowth}
      title={`Subculture passage ${passage.number}`}
      description={`Records passage ${passage.number + 1}, grown from passage ${passage.number}. Record how the culture is grown.`}
      confirmLabel="Record subculture"
      label="Growth conditions of the subculture"
      pending={subculture.isPending}
      send={(growth, options) => subculture.mutate({ sourcePassage: passage.public_id, growth }, options)}
      open={open}
      onClose={onClose}
      onExited={onExited}
    />
  )
}
