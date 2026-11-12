import type { ReactNode } from 'react'
import type { FieldErrors, UseFormRegisterReturn } from 'react-hook-form'
import { SelectField, TextField } from '@/components/ui'
import { useBoxTypes } from '../api/queries'
import { type EditUnitForm, isRoot, KIND_LABELS, RISK_GROUP_CHOICES, type Unit, type UnitKind } from '../schemas'

type FieldName = keyof EditUnitForm
type Register = (name: FieldName) => UseFormRegisterReturn

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

type KindFieldProps = { kinds: readonly UnitKind[]; register: (name: 'kind') => UseFormRegisterReturn; error: string | undefined }

/** The kind to add, asked only when the parent may hold more than one. */
export function KindField({ kinds, register, error }: KindFieldProps) {
  if (kinds.length <= 1) return null
  return (
    <SelectField
      label="Kind"
      options={kinds.map((k) => ({ value: k, label: KIND_LABELS[k] }))}
      // oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog)
      autoFocus
      error={error}
      {...register('kind')}
    />
  )
}

type SlotFieldProps = { parent: Pick<Unit, 'name'> | null; register: UseFormRegisterReturn; error: string | undefined }

/** The numbered place in the parent: only a unit being added into another one has it. */
export function SlotField({ parent, register, error }: SlotFieldProps) {
  if (parent === null) return null
  return <TextField label="Slot" hint={`Its numbered place in ${parent.name}, if it has one.`} inputMode="numeric" autoComplete="off" error={error} {...register} />
}

type UnitFieldsProps = {
  kind: UnitKind
  /** The slot field, between the box type and the temperature, where a unit is added into another. */
  slot?: ReactNode
  /** Name takes the focus unless the kind select is there to take it. */
  focusName: boolean
  register: Register
  errors: FieldErrors<EditUnitForm>
}

/** The fields a unit has whether it is added or changed, in the order a person fills them. */
export function UnitFields({ kind, slot, focusName, register, errors }: UnitFieldsProps) {
  const root = isRoot(kind)
  return (
    <>
      {/* oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog) */}
      <TextField label="Name" autoFocus={focusName} autoComplete="off" error={errors.name?.message} {...register('name')} />
      {kind === 'box' && <BoxTypeField error={errors.box_type?.message} {...register('box_type')} />}
      {slot}
      {root && <TextField label="Temperature (°C)" hint="Optional, whole degrees." inputMode="numeric" autoComplete="off" error={errors.temperature_c?.message} {...register('temperature_c')} />}
      <SelectField label="Highest risk group" hint="What it and everything in it may hold." options={capOptions(root)} error={errors.max_risk_group?.message} {...register('max_risk_group')} />
      <TextField label="Barcode" hint="Optional, the label on the unit." autoComplete="off" error={errors.barcode?.message} {...register('barcode')} />
    </>
  )
}
