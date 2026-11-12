import type { FieldErrors, UseFormRegister, UseFormSetValue } from 'react-hook-form'
import { SelectField, Stack, TextField, Typography } from '@/components/ui'
import { type BoxChoice, boxOption, METHOD_LABELS, type Passage, type PlaceForm, type PreserveForm, PURPOSE_LABELS, rowLabel } from '../schemas'

const choose = (label: string) => ({ value: '', label })
const labelled = (labels: Record<string, string>) => Object.entries(labels).map(([value, label]) => ({ value, label }))
const METHOD_OPTIONS = labelled(METHOD_LABELS)
const PURPOSE_OPTIONS = labelled(PURPOSE_LABELS)

const passageLabel = (p: Passage) => (p.number === 0 ? 'Passage 0, as received' : `Passage ${p.number}`)

/** What stands in place of the box fields while the boxes load. A failed load says so in the dialog, so nothing stands here. */
export function BoxesWait({ failed }: { failed: boolean | undefined }) {
  return failed ? null : <Typography>Loading the boxes…</Typography>
}

type PreserveFieldsProps = {
  register: UseFormRegister<PreserveForm>
  errors: FieldErrors<PreserveForm>
  passages: readonly Passage[]
  boxes: readonly BoxChoice[] | undefined
  boxesFailed: boolean | undefined
}

/** The batch to preserve: its passage, how and why, the protectant, the date, the number of vials, and the box if they go in now. */
export function PreserveFields({ register, errors, passages, boxes, boxesFailed }: PreserveFieldsProps) {
  return (
    <>
      <SelectField
        label="Passage"
        options={[choose('Choose'), ...passages.toReversed().map((p) => ({ value: p.public_id, label: passageLabel(p) }))]}
        // oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog)
        autoFocus
        error={errors.passage?.message}
        {...register('passage')}
      />
      <SelectField label="Method" options={METHOD_OPTIONS} error={errors.method?.message} {...register('method')} />
      <SelectField label="Purpose" hint="Seed stock is never distributed." options={PURPOSE_OPTIONS} error={errors.purpose?.message} {...register('purpose')} />
      <TextField label="Protectant" hint="For example 10 % glycerol, or skim milk. Optional." autoComplete="off" error={errors.cryoprotectant?.message} {...register('cryoprotectant')} />
      <TextField label="Preserved on" hint="YYYY-MM-DD" autoComplete="off" error={errors.preserved_on?.message} {...register('preserved_on')} />
      <TextField label="Number of vials" hint="1 to 200" inputMode="numeric" autoComplete="off" error={errors.vial_count?.message} {...register('vial_count')} />
      {boxes ? (
        <SelectField label="Box" hint="Optional. Placed later otherwise." options={[choose('Do not place them yet'), ...boxes.map(boxOption)]} error={errors.box?.message} {...register('box')} />
      ) : (
        <BoxesWait failed={boxesFailed} />
      )}
    </>
  )
}

/** The numbers 1 to n as options: the rows of a box, by their letters, or its columns. */
const rangeOptions = (n: number | undefined, label: (i: number) => string) => Array.from({ length: n ?? 0 }, (_, i) => ({ value: String(i + 1), label: label(i + 1) }))

type PlaceFieldsProps = {
  register: UseFormRegister<PlaceForm>
  errors: FieldErrors<PlaceForm>
  setValue: UseFormSetValue<PlaceForm>
  boxes: readonly BoxChoice[]
  /** The box chosen so far, whose rows and columns the position is chosen from. */
  box: BoxChoice | undefined
}

/** The box and the position in it. Another box has other rows and columns: the position is chosen again. */
export function PlaceFields({ register, errors, setValue, boxes, box }: PlaceFieldsProps) {
  const first = choose(box ? 'Choose' : 'Box first')
  return (
    <>
      <SelectField
        label="Box"
        options={[choose('Choose'), ...boxes.map(boxOption)]}
        // oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog)
        autoFocus
        error={errors.box?.message}
        {...register('box', {
          onChange: () => {
            setValue('row', '')
            setValue('col', '')
          },
        })}
      />
      <Stack direction="row" spacing={2}>
        <SelectField label="Row" options={[first, ...rangeOptions(box?.rows, rowLabel)]} error={errors.row?.message} {...register('row')} />
        <SelectField label="Column" options={[first, ...rangeOptions(box?.cols, String)]} error={errors.col?.message} {...register('col')} />
      </Stack>
    </>
  )
}
