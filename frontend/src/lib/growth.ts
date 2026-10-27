import { keepPreviousData, queryOptions } from '@tanstack/react-query'
import { z } from 'zod'
import type { components } from '@/api/schema'
import { api, unwrap } from './api'
import { sharedKeys } from './shared-keys'

type Schemas = components['schemas']
export type Growth = Schemas['GrowthOutput']
export type Medium = Schemas['MediumOutput']
export type MediumBrief = Schemas['MediumBrief']
export type Atmosphere = Schemas['AtmosphereEnum']
export type GrowthBody = Schemas['GrowthInputRequest']

/**
 * How a strain is grown (#79): the medium from the lab's list, a temperature in whole degrees
 * Celsius (one value or a range) and an atmosphere. The same fields sit on a strain and, as
 * what one passage used, on a passage. The strain page, the passage list and the dialogs of both
 * features read them, so the vocabulary, the text and the form fields live here.
 *
 * The atmosphere words are the three the culture collections use for a growth condition
 * (DSMZ MediaDive, CCM and ATCC product sheets); the server holds the same list.
 */
export const ATMOSPHERES = ['aerobic', 'microaerophilic', 'anaerobic'] as const satisfies readonly Atmosphere[]
export const ATMOSPHERE_LABELS: Record<Atmosphere, string> = {
  aerobic: 'Aerobic',
  microaerophilic: 'Microaerophilic',
  anaerobic: 'Anaerobic',
}
export const MIN_TEMPERATURE_C = 0
export const MAX_TEMPERATURE_C = 125

/** "28 °C" or "25 to 30 °C"; empty when none is recorded. */
export function temperatureText(growth: Pick<Growth, 'temperature_low_c' | 'temperature_high_c'>): string {
  const { temperature_low_c: low, temperature_high_c: high } = growth
  if (low === null) return ''
  return high === null || high === low ? `${low} °C` : `${low} to ${high} °C`
}

export const mediumName = (medium: MediumBrief) => (medium.retired_at ? `${medium.name} (retired)` : medium.name)

/** The medium, temperature and atmosphere in one line, or a note that none is recorded. */
export function growthText(growth: Growth): string {
  const parts = [growth.medium ? mediumName(growth.medium) : '', temperatureText(growth), growth.atmosphere ? ATMOSPHERE_LABELS[growth.atmosphere] : ''].filter(Boolean)
  return parts.length > 0 ? parts.join(', ') : 'Not recorded'
}

export const noGrowth = (growth: Growth): boolean => growth.medium === null && growth.temperature_low_c === null && growth.atmosphere === ''

// The lab's media (#79): one page of 200 holds a lab's list.
export const MEDIA_ALL = { limit: 200, offset: 0 }
export const mediaListOptions = (labId: string) =>
  queryOptions({
    queryKey: sharedKeys.mediaList(labId, MEDIA_ALL),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/labs/{lab_public_id}/media/', { signal, params: { path: { lab_public_id: labId }, query: MEDIA_ALL } })),
    placeholderData: keepPreviousData,
  })

/**
 * The media to choose from: those in use, plus the retired one the thing being edited already
 * has (a retired medium stays where it was used, and is not given to anything new).
 */
export function mediumChoices(media: readonly Medium[], current: MediumBrief | null): Medium[] {
  return media.filter((m) => m.retired_at === null || m.public_id === current?.public_id)
}

/** Why, for a change that is kept in the audit trail. */
export const reasonSchema = z.string().trim().min(1, 'Say why').max(2000, 'Use at most 2000 characters')

// The form: strings as typed. Limits mirror the server, which still decides.
const WHOLE = /^\d{1,3}$/
export const growthShape = {
  medium: z.string(),
  temperature_low_c: z.string().trim(),
  temperature_high_c: z.string().trim(),
  atmosphere: z.enum(['', ...ATMOSPHERES]),
}
export const growthSchema = z.object(growthShape).superRefine(checkTemperatures)
export type GrowthForm = z.input<typeof growthSchema>

/** The two temperature boxes together, for a schema that holds them next to other fields. */
export function checkTemperatures(form: { temperature_low_c: string; temperature_high_c: string }, ctx: z.RefinementCtx) {
  const { temperature_low_c: low, temperature_high_c: high } = form
  const range = `Use whole degrees from ${MIN_TEMPERATURE_C} to ${MAX_TEMPERATURE_C} °C`
  const bad = (value: string) => !WHOLE.test(value) || Number(value) < MIN_TEMPERATURE_C || Number(value) > MAX_TEMPERATURE_C
  if (low === '' && high !== '') ctx.addIssue({ code: 'custom', path: ['temperature_low_c'], message: 'Enter the low end too' })
  if (low !== '' && bad(low)) ctx.addIssue({ code: 'custom', path: ['temperature_low_c'], message: range })
  if (high !== '' && bad(high)) ctx.addIssue({ code: 'custom', path: ['temperature_high_c'], message: range })
  if (low !== '' && high !== '' && !bad(low) && !bad(high) && Number(high) < Number(low)) {
    ctx.addIssue({ code: 'custom', path: ['temperature_high_c'], message: 'The high end is below the low end' })
  }
}

export const growthDefaults = (growth: Growth): GrowthForm => ({
  medium: growth.medium?.public_id ?? '',
  temperature_low_c: growth.temperature_low_c === null ? '' : String(growth.temperature_low_c),
  temperature_high_c: growth.temperature_high_c === null || growth.temperature_high_c === growth.temperature_low_c ? '' : String(growth.temperature_high_c),
  atmosphere: growth.atmosphere,
})

/** The form's fields as the API takes them: empty means none. */
export function growthBody(form: GrowthForm): GrowthBody {
  return {
    medium: form.medium === '' ? null : form.medium,
    temperature_low_c: form.temperature_low_c === '' ? null : Number(form.temperature_low_c),
    temperature_high_c: form.temperature_high_c === '' ? null : Number(form.temperature_high_c),
    atmosphere: form.atmosphere,
  }
}

/** The fields the server names for a growth failure. */
export const GROWTH_FIELDS = ['medium', 'temperature_low_c', 'temperature_high_c', 'atmosphere'] as const
