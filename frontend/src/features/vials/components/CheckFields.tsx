import type { FieldErrors, UseFormRegister, UseFormSetValue } from 'react-hook-form'
import { SelectField, Stack, TextField, Typography } from '@/components/ui'
import {
  type Batch,
  type BatchCheck,
  CHECK_KINDS,
  CHECK_METHOD_LABELS,
  type CheckForm,
  KIND_LABELS,
  METHODS_BY_KIND,
  RESULT_LABELS,
  STAGE_LABELS,
  UNIT_LABELS,
  type Vial,
} from '../schemas'

const labelled = (labels: Record<string, string>) => Object.entries(labels).map(([value, label]) => ({ value, label }))
const KIND_OPTIONS = CHECK_KINDS.map((value) => ({ value, label: KIND_LABELS[value] }))
const STAGE_OPTIONS = labelled(STAGE_LABELS)
const RESULT_OPTIONS = labelled(RESULT_LABELS)
const UNIT_OPTIONS = [{ value: '', label: 'None' }, ...labelled(UNIT_LABELS)]

/** Says so when the list holds only the first vials of the batch: the others cannot be named here. */
const vialHint = (shown: number, total: number | undefined) =>
  total !== undefined && total > shown
    ? `Optional. Used up by the check. Only the first ${shown} of the ${total} vials of the batch are listed.`
    : 'Optional. Used up by the check.'

/** The vials the check may name: the batch's available ones, and the ones an earlier check used. */
function vialOptionsOf(batch: Batch, vials: readonly Vial[] | undefined, checks: readonly BatchCheck[] | undefined) {
  const available = (vials ?? []).filter((v) => v.batch === batch.public_id && v.status === 'available')
  const used = new Map((checks ?? []).flatMap((c) => (c.vial && c.vial_label ? [[c.vial, c.vial_label] as const] : [])))
  return [
    { value: '', label: 'None named' },
    ...available.map((v) => ({ value: v.public_id, label: v.label })),
    ...[...used].map(([id, label]) => ({ value: id, label: `${label}, used by an earlier check` })),
  ]
}

type Props = {
  register: UseFormRegister<CheckForm>
  errors: FieldErrors<CheckForm>
  setValue: UseFormSetValue<CheckForm>
  kind: CheckForm['kind']
  batch: Batch
  vials: readonly Vial[] | undefined
  vialsTotal: number | undefined
  checks: readonly BatchCheck[] | undefined
}

/** The vial the check used up. Mounted once its options are there, so a chosen vial is never lost to a late list. */
function VialField({ register, errors, batch, vials, vialsTotal, checks }: Pick<Props, 'register' | 'errors' | 'batch' | 'vials' | 'vialsTotal' | 'checks'>) {
  if (vials === undefined) return <Typography>Loading the vials of the batch…</Typography>
  return <SelectField label="Vial checked" hint={vialHint(vials.length, vialsTotal)} options={vialOptionsOf(batch, vials, checks)} error={errors.vial?.message} {...register('vial')} />
}

/** The kind of check. A new kind brings its own methods, so the method follows it. */
function KindField({ register, errors, setValue }: Pick<Props, 'register' | 'errors' | 'setValue'>) {
  return (
    <SelectField
      label="Kind"
      options={KIND_OPTIONS}
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
  )
}

/** The fields of a check: what kind and how, when, the result and its value, the vial used up, a note. */
export function CheckFields({ register, errors, setValue, kind, batch, vials, vialsTotal, checks }: Props) {
  return (
    <>
      <KindField register={register} errors={errors} setValue={setValue} />
      <SelectField label="Stage" options={STAGE_OPTIONS} error={errors.stage?.message} {...register('stage')} />
      <TextField label="Checked on" hint="YYYY-MM-DD" autoComplete="off" error={errors.checked_on?.message} {...register('checked_on')} />
      <SelectField
        // A new kind brings other options: mounted again, it shows the method the kind set.
        key={kind}
        label="Method"
        options={METHODS_BY_KIND[kind].map((value) => ({ value, label: CHECK_METHOD_LABELS[value] }))}
        error={errors.method?.message}
        {...register('method')}
      />
      <TextField label="Method details" hint="Medium, temperature, gene. Required for Other." autoComplete="off" error={errors.method_detail?.message} {...register('method_detail')} />
      <SelectField label="Result" hint="Reduced counts as passed for a release. Say in the note what was seen." options={RESULT_OPTIONS} error={errors.result?.message} {...register('result')} />
      <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap' }}>
        <TextField label="Value" hint="Optional, as 2.1e8" inputMode="decimal" autoComplete="off" error={errors.value?.message} {...register('value')} />
        <SelectField label="Unit" options={UNIT_OPTIONS} error={errors.unit?.message} {...register('unit')} />
      </Stack>
      <VialField register={register} errors={errors} batch={batch} vials={vials} vialsTotal={vialsTotal} checks={checks} />
      <TextField label="Note" hint="What was seen. Required for a reduced result. Name no person." multiline minRows={2} error={errors.note?.message} {...register('note')} />
    </>
  )
}
