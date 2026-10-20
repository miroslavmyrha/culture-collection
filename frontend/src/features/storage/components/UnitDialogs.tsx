import { zodResolver } from '@hookform/resolvers/zod'
import { useId, useState } from 'react'
import { type FieldValues, type Path, type UseFormRegisterReturn, type UseFormSetError, useForm, useWatch } from 'react-hook-form'
import { ConfirmDialog, SelectField, Stack, TextField } from '@/components/ui'
import { isApiError } from '@/lib/api'
import { applyServerErrors } from '@/lib/forms'
import { useCreateUnit, useEditUnit, useMoveUnit, useSetUnitStatus } from '../api/mutations'
import { useBoxTypes, useUnitTree } from '../api/queries'
import {
  createBody,
  type CreateUnitForm,
  createUnitSchema,
  editUnitSchema,
  type EditUnitForm,
  emptyFields,
  fieldsBody,
  HOLDS,
  isRoot,
  KIND_LABELS,
  KIND_WORDS,
  moveBody,
  type MoveUnitForm,
  moveUnitSchema,
  RISK_GROUP_CHOICES,
  type StatusForm,
  statusSchema,
  type Unit,
  type UnitKind,
  type UnitRow,
} from '../schemas'
import { storageError } from '../storageErrors'

type Visibility = { open: boolean; onClose: () => void; onExited: () => void }

const REASON_HINT = 'Stored for good with the change. Name no person.'
const FIELDS = ['name', 'barcode', 'temperature_c', 'max_risk_group', 'box_type'] as const

/**
 * The failure of a dialog's request: field errors on their fields (focused), everything else
 * as the dialog's own message. Returns that message, or undefined when a field took it.
 */
function placeError<T extends FieldValues>(
  error: unknown,
  fields: readonly Path<T>[],
  setError: UseFormSetError<T>,
  reasonField?: Path<T>,
): string | undefined {
  // A reason of spaces only passes the form and fails the server: say so on the field.
  if (isApiError(error) && error.code === 'reason_required' && reasonField) {
    setError(reasonField, { type: 'server', message: 'Say why' }, { shouldFocus: true })
    return undefined
  }
  return applyServerErrors(error, fields, setError) ? undefined : storageError(error)
}

function capOptions(root: boolean) {
  const groups = RISK_GROUP_CHOICES.map((value) => ({ value, label: `Risk group ${value}` }))
  return [{ value: '', label: root ? 'Choose' : 'As the unit holding it' }, ...groups]
}

/** The box types staff keep, as a select; spread register('box_type') on it. */
function BoxTypeField({ error, ...registered }: UseFormRegisterReturn & { error: string | undefined }) {
  const types = useBoxTypes()
  const options = [
    { value: '', label: types.isPending ? 'Loading the box types…' : 'Choose' },
    ...(types.data?.results ?? []).map((t) => ({ value: t.public_id, label: t.name })),
  ]
  // A failed refresh keeps the types already loaded: only a failed first load is an error.
  const failed = types.data === undefined && types.isError ? 'The box types could not be loaded. Close and try again.' : undefined
  return <SelectField label="Box type" hint="Its rows and columns become the box's size." options={options} error={error ?? failed} {...registered} />
}

type CreateProps = Visibility & {
  labId: string
  /** The unit it goes into; null for a freezer or tank. */
  parent: Pick<Unit, 'public_id' | 'kind' | 'name'> | null
  onCreated: (unit: Unit) => void
}

/** A freezer or tank on its own, or what the parent may hold, as the server's kind spec says. */
export function CreateUnitDialog({ labId, parent, open, onClose, onExited, onCreated }: CreateProps) {
  const create = useCreateUnit(labId)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const kinds: readonly UnitKind[] = parent ? HOLDS[parent.kind] : ['freezer', 'ln2_tank']
  const first = kinds[0] ?? 'freezer'
  const { control, register, handleSubmit, formState, setError } = useForm<CreateUnitForm>({
    resolver: zodResolver(createUnitSchema),
    defaultValues: { kind: first, slot: '', ...emptyFields() },
  })
  const kind = useWatch({ control, name: 'kind' })
  const errors = formState.errors
  const onSubmit = handleSubmit((values) => {
    setFailure(undefined)
    create.mutate(createBody(values, parent?.public_id ?? null), {
      onSuccess: (unit) => onCreated(unit),
      // A refused parent has no field here: it shows as the dialog's message.
      onError: (error) => setFailure(placeError(error, ['kind', 'slot', ...FIELDS], setError)),
    })
  })
  const what = kinds.map((k) => KIND_WORDS[k]).join(' or ')
  const title = parent ? `Add a ${what} to ${parent.name}` : 'Add a freezer or tank'
  return (
    <ConfirmDialog
      open={open}
      title={title}
      description={parent ? `It goes into ${parent.name}.` : 'A freezer or tank stands on its own and states the highest risk group it may hold.'}
      confirmLabel="Add"
      form={formId}
      pending={create.isPending}
      error={failure ?? errors.root?.server?.message}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label={title} spacing={2} sx={{ mt: 2 }}>
        {kinds.length > 1 && (
          <SelectField
            label="Kind"
            options={kinds.map((k) => ({ value: k, label: KIND_LABELS[k] }))}
            // oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog)
            autoFocus
            error={errors.kind?.message}
            {...register('kind')}
          />
        )}
        {/* oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog) */}
        <TextField label="Name" autoFocus={kinds.length === 1} autoComplete="off" error={errors.name?.message} {...register('name')} />
        {kind === 'box' && <BoxTypeField error={errors.box_type?.message} {...register('box_type')} />}
        {parent && <TextField label="Slot" hint={`Its numbered place in ${parent.name}, if it has one.`} inputMode="numeric" autoComplete="off" error={errors.slot?.message} {...register('slot')} />}
        {isRoot(kind) && <TextField label="Temperature (°C)" hint="Optional, whole degrees." inputMode="numeric" autoComplete="off" error={errors.temperature_c?.message} {...register('temperature_c')} />}
        <SelectField label="Highest risk group" hint="What it and everything in it may hold." options={capOptions(isRoot(kind))} error={errors.max_risk_group?.message} {...register('max_risk_group')} />
        <TextField label="Barcode" hint="Optional, the label on the unit." autoComplete="off" error={errors.barcode?.message} {...register('barcode')} />
      </Stack>
    </ConfirmDialog>
  )
}

type UnitProps = Visibility & { labId: string; unit: Unit }

export function EditUnitDialog({ labId, unit, open, onClose, onExited }: UnitProps) {
  const edit = useEditUnit(labId, unit.public_id)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const { register, handleSubmit, formState, setError } = useForm<EditUnitForm>({
    resolver: zodResolver(editUnitSchema(unit.kind)),
    defaultValues: emptyFields(unit),
  })
  const errors = formState.errors
  const onSubmit = handleSubmit((values) => {
    setFailure(undefined)
    edit.mutate(fieldsBody(unit.kind, values), {
      onSuccess: onClose,
      onError: (error) => setFailure(placeError(error, FIELDS, setError)),
    })
  })
  return (
    <ConfirmDialog
      open={open}
      title={`Change ${unit.name}`}
      description={unit.kind === 'box' ? 'A box takes the size of a new type only while no position in it is occupied.' : 'Its name, temperature, risk group and barcode.'}
      confirmLabel="Save"
      form={formId}
      pending={edit.isPending}
      error={failure ?? errors.root?.server?.message}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label={`Change ${unit.name}`} spacing={2} sx={{ mt: 2 }}>
        {/* oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog) */}
        <TextField label="Name" autoFocus autoComplete="off" error={errors.name?.message} {...register('name')} />
        {unit.kind === 'box' && <BoxTypeField error={errors.box_type?.message} {...register('box_type')} />}
        {isRoot(unit.kind) && <TextField label="Temperature (°C)" hint="Optional, whole degrees." inputMode="numeric" autoComplete="off" error={errors.temperature_c?.message} {...register('temperature_c')} />}
        <SelectField label="Highest risk group" hint="What it and everything in it may hold." options={capOptions(isRoot(unit.kind))} error={errors.max_risk_group?.message} {...register('max_risk_group')} />
        <TextField label="Barcode" hint="Optional, the label on the unit." autoComplete="off" error={errors.barcode?.message} {...register('barcode')} />
      </Stack>
    </ConfirmDialog>
  )
}

/** "Freezer A / Rack 1": a unit by its path, for the list of places. */
function pathName(row: UnitRow, byId: ReadonlyMap<string, UnitRow>): string {
  const names = [row.name]
  for (let up = row.parent ? byId.get(row.parent) : undefined; up; up = up.parent ? byId.get(up.parent) : undefined) names.unshift(up.name)
  return names.join(' / ')
}

/**
 * The units this one may go into: active, and of a kind that may hold it. No kind holds its
 * own kind, so neither the unit nor anything below it is offered; the server refuses a cycle
 * on the field anyway.
 */
export function moveTargets(unit: Pick<Unit, 'kind'>, rows: readonly UnitRow[]) {
  const byId = new Map(rows.map((row) => [row.public_id, row]))
  return rows
    .filter((row) => row.status === 'active' && HOLDS[row.kind].includes(unit.kind))
    .map((row) => ({ value: row.public_id, label: pathName(row, byId) }))
    .toSorted((a, b) => a.label.localeCompare(b.label))
}

export function MoveUnitDialog({ labId, unit, open, onClose, onExited }: UnitProps) {
  const move = useMoveUnit(labId, unit.public_id)
  const tree = useUnitTree(labId)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const { register, handleSubmit, formState, setError } = useForm<MoveUnitForm>({
    resolver: zodResolver(moveUnitSchema),
    defaultValues: { parent: '', slot: '' },
  })
  const errors = formState.errors
  const targets = moveTargets(unit, tree.data ?? []).filter((target) => target.value !== unit.parent)
  const placeholder = tree.isPending ? 'Loading the storage…' : targets.length === 0 ? 'No unit can take it' : 'Choose'
  const onSubmit = handleSubmit((values) => {
    setFailure(undefined)
    move.mutate(moveBody(values), {
      onSuccess: onClose,
      onError: (error) => setFailure(placeError(error, ['parent', 'slot'], setError)),
    })
  })
  return (
    <ConfirmDialog
      open={open}
      title={`Move ${unit.name}`}
      description={`Everything in ${unit.name} moves with it.`}
      confirmLabel="Move"
      form={formId}
      pending={move.isPending}
      error={failure ?? errors.root?.server?.message ?? (tree.data === undefined && tree.isError ? storageError(tree.error) : undefined)}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label={`Move ${unit.name}`} spacing={2} sx={{ mt: 2 }}>
        <SelectField
          label="Into"
          options={[{ value: '', label: placeholder }, ...targets]}
          // oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog)
          autoFocus
          error={errors.parent?.message}
          {...register('parent')}
        />
        <TextField label="Slot" hint="Its numbered place there, if it has one." inputMode="numeric" autoComplete="off" error={errors.slot?.message} {...register('slot')} />
      </Stack>
    </ConfirmDialog>
  )
}

type StatusProps = UnitProps & { to: 'active' | 'out_of_service' | 'retired' }

const STATUS_TEXT = {
  active: { title: (name: string) => `Put ${name} back in service`, description: 'Units and vials may go into it again.', confirm: 'Back in service' },
  out_of_service: {
    title: (name: string) => `Put ${name} out of service`,
    description: 'Nothing new goes into it or into anything it holds until it is back in service.',
    confirm: 'Out of service',
  },
  retired: {
    title: (name: string) => `Retire ${name}?`,
    description: 'A retired unit stays in the history but changes no more and takes nothing. This cannot be undone.',
    confirm: 'Retire',
  },
} as const

/** Out of service, back in service, or retired for good: each with a reason. */
export function UnitStatusDialog({ labId, unit, to, open, onClose, onExited }: StatusProps) {
  const change = useSetUnitStatus(labId, unit.public_id)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const { register, handleSubmit, formState, setError } = useForm<StatusForm>({
    resolver: zodResolver(statusSchema),
    defaultValues: { reason: '' },
  })
  const text = STATUS_TEXT[to]
  const onSubmit = handleSubmit((values) => {
    setFailure(undefined)
    change.mutate(
      { status: to, reason: values.reason.trim() },
      { onSuccess: onClose, onError: (error) => setFailure(placeError(error, ['reason'], setError, 'reason')) },
    )
  })
  const form = (
    <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label={text.title(unit.name)} spacing={2} sx={{ mt: 2 }}>
      {/* oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog) */}
      <TextField label="Reason" hint={REASON_HINT} multiline minRows={2} autoFocus={to !== 'retired'} error={formState.errors.reason?.message} {...register('reason')} />
    </Stack>
  )
  const common = { open, title: text.title(unit.name), confirmLabel: text.confirm, form: formId, pending: change.isPending, error: failure, onClose, onExited }
  // Retiring is final: an alertdialog that opens on Cancel and names the consequence.
  return to === 'retired' ? (
    <ConfirmDialog {...common} destructive description={text.description}>
      {form}
    </ConfirmDialog>
  ) : (
    <ConfirmDialog {...common} description={text.description}>
      {form}
    </ConfirmDialog>
  )
}
