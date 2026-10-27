import type { UseFormRegister } from 'react-hook-form'
import { SelectField, Stack, TextField, Typography } from '@/components/ui'
import { ATMOSPHERE_LABELS, ATMOSPHERES, type GrowthForm, type Medium, type MediumBrief, mediumChoices } from '@/lib/growth'

type Name = keyof GrowthForm
type Errors = Partial<Record<Name, { message?: string | undefined } | undefined>>

type Props = {
  /** Pass the form's own register: `(name) => register(name)`. */
  register: (name: Name) => ReturnType<UseFormRegister<GrowthForm>>
  errors: Errors
  /** The lab's media; undefined while they load. */
  media: readonly Medium[] | undefined
  mediaFailed?: boolean
  /** The medium the thing being edited has now: offered also when retired. */
  current: MediumBrief | null
  /** Put the first field in focus (a dialog opens on its first field). */
  autoFocus?: boolean
}

/**
 * The growth conditions of a strain or a passage as form fields (#79): a medium of the lab, a
 * whole-degree temperature (one value, or a range with the high end), an atmosphere. Each may
 * stay empty. A failed load of the media is no empty list, so it says so instead of offering
 * "No medium".
 */
export function GrowthFields({ register, errors, media, mediaFailed = false, current, autoFocus = false }: Props) {
  if (media === undefined && !mediaFailed) return <Typography>Loading the media…</Typography>
  const choices = [
    { value: '', label: 'No medium' },
    ...mediumChoices(media ?? [], current).map((m) => ({ value: m.public_id, label: m.retired_at ? `${m.name} (retired)` : m.name })),
  ]
  return (
    <>
      {mediaFailed ? (
        <Typography role="alert">Could not load the media. Close this dialog and try again.</Typography>
      ) : (
        <SelectField
          label="Medium"
          hint="From the lab's list of media."
          options={choices}
          // oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog)
          autoFocus={autoFocus}
          error={errors.medium?.message}
          {...register('medium')}
        />
      )}
      <Stack direction="row" spacing={2}>
        <TextField label="Temperature °C" hint="Whole degrees, 0 to 125." inputMode="numeric" autoComplete="off" error={errors.temperature_low_c?.message} {...register('temperature_low_c')} />
        <TextField label="Up to °C" hint="Only for a range." inputMode="numeric" autoComplete="off" error={errors.temperature_high_c?.message} {...register('temperature_high_c')} />
      </Stack>
      <SelectField
        label="Atmosphere"
        options={[{ value: '', label: 'Not recorded' }, ...ATMOSPHERES.map((value) => ({ value, label: ATMOSPHERE_LABELS[value] }))]}
        error={errors.atmosphere?.message}
        {...register('atmosphere')}
      />
    </>
  )
}
