import { z } from 'zod'
import type { components } from '@/api/schema'
import { pageDefaults } from '@/lib/paging'
import { isCountry } from '@/lib/countries'

type Schemas = components['schemas']
export type StrainRow = Schemas['StrainListOutput']
export type Strain = Schemas['StrainDetailOutput']
export type Taxon = Schemas['TaxonBrief']
export type TaxonDetail = Schemas['TaxonOutput']
export type RiskGroup = Schemas['RiskGroup']
export type Pathogenicity = Schemas['Pathogenicity']
export type RestrictionKind = Schemas['RestrictionKind']
export type StrainStatus = Schemas['StrainStatus']
export type CountryCode = Schemas['CountryCode']
export type Role = Schemas['Role']
export type Terms = Schemas['TermsOutput']
export type HistoryLine = Schemas['HistoryLine']

/** Curators and managers write strains (strains.manage). The server decides; this only hides. */
export const canManageStrains = (role: Role | undefined): boolean => role === 'curator' || role === 'manager'
/**
 * A restriction ends by two people (#105, ADR 0009): a curator or a manager proposes it, a manager
 * other than the proposer confirms it (strains.confirm_restriction_end).
 */
export const canConfirmRestrictionEnd = (role: Role | undefined): boolean => role === 'manager'

export const RISK_GROUPS = [1, 2, 3, 4] as const satisfies readonly RiskGroup[]
export const PATHOGENICITY_LABELS: Record<Pathogenicity, string> = {
  unknown: 'Unknown',
  none_known: 'No pathogenicity known',
  pathogenic: 'Pathogenic',
}
export const STATUS_LABELS: Record<StrainStatus, string> = {
  pending: 'Pending',
  active: 'Active',
  restricted: 'Restricted',
  deaccessioned: 'Deaccessioned',
}
/** Short names for tables and filters; the field hints name the lists they come from. */
export const RESTRICTION_LABELS: Record<RestrictionKind, string> = {
  cz_vrat: 'Highly risky agent (VRAT)',
  cz_rat: 'Risky agent (RAT)',
  dual_use: 'Dual-use item',
  quarantine_pest: 'Quarantine pest',
  gmo: 'GMO in contained use',
}
export const RESTRICTION_KINDS = ['cz_vrat', 'cz_rat', 'dual_use', 'quarantine_pest', 'gmo'] as const satisfies readonly RestrictionKind[]
/** Where the list entry of each kind is read (ADR 0009). */
export const REFERENCE_HINTS: Record<RestrictionKind, string> = {
  cz_vrat: 'The entry in Annex 1 of decree 474/2002 Sb.',
  cz_rat: 'The entry in Annex 2 of decree 474/2002 Sb.',
  dual_use: 'The Annex I entry of Regulation (EU) 2021/821, for example 1C351.c',
  quarantine_pest: 'The entry in Annex II of Implementing Regulation (EU) 2019/2072',
  gmo: 'The notification or permit reference under act 78/2004 Sb.',
}
export const GMO_CATEGORIES = [1, 2, 3, 4] as const
export const GMO_CATEGORY_LABELS: Record<number, string> = { 1: 'I', 2: 'II', 3: 'III', 4: 'IV' }

export const options = <T extends string | number>(labels: Record<T, string>, values: readonly T[]) =>
  values.map((value) => ({ value: String(value), label: labels[value] }))

export { countryName } from '@/lib/countries'
export { actorLabel, moment } from '@/lib/activity'

export const taxonLabel = (taxon: Pick<Taxon, 'name' | 'authority'>) => (taxon.authority ? `${taxon.name} ${taxon.authority}` : taxon.name)

// The list's URL state. Defaults stay out of the URL; a bad value falls back to the default.
const uuid = z.uuid()
export const strainListDefaults = {
  ...pageDefaults,
  taxon: undefined,
  risk_group: undefined,
  status: undefined,
  restriction: undefined,
  search: undefined,
}
export const strainListSearch = z.object({
  limit: z.number().int().min(1).max(200).default(pageDefaults.limit).catch(pageDefaults.limit),
  offset: z.number().int().min(0).default(pageDefaults.offset).catch(pageDefaults.offset),
  taxon: uuid.optional().catch(undefined),
  risk_group: z.literal([1, 2, 3, 4]).optional().catch(undefined),
  status: z.enum(['pending', 'active', 'restricted', 'deaccessioned']).optional().catch(undefined),
  restriction: z.enum(['cz_vrat', 'cz_rat', 'dual_use', 'quarantine_pest', 'gmo']).optional().catch(undefined),
  search: z.string().trim().max(200).optional().catch(undefined),
})
export type StrainListParams = z.output<typeof strainListSearch>
export type StrainFilters = Omit<StrainListParams, 'limit' | 'offset'>
export const hasFilters = (params: StrainListParams) =>
  params.taxon !== undefined || params.risk_group !== undefined || params.status !== undefined || params.restriction !== undefined || Boolean(params.search)

// Forms. Limits mirror the backend; the server still decides and its errors map back.
const required = (message: string) => z.string().trim().min(1, message)
const choice = <T extends string>(values: readonly [T, ...T[]], message: string) => z.enum(values, message)

export const restrictionSchema = z
  .object({
    kind: choice(['cz_vrat', 'cz_rat', 'dual_use', 'quarantine_pest', 'gmo'], 'Choose a kind'),
    reference: required('Enter the list entry').max(100, 'Use at most 100 characters'),
    act: z.string().trim().max(30, 'Use at most 30 characters'),
    gmo_category: z.string(),
  })
  .superRefine((value, ctx) => {
    if (value.kind === 'dual_use' && !value.act) ctx.addIssue({ code: 'custom', path: ['act'], message: 'Enter the act Annex I was read in' })
    if (value.kind === 'gmo' && !value.gmo_category) ctx.addIssue({ code: 'custom', path: ['gmo_category'], message: 'Choose the category' })
  })
export type RestrictionForm = z.input<typeof restrictionSchema>
export const emptyRestriction: RestrictionForm = { kind: 'cz_rat', reference: '', act: '', gmo_category: '' }

const isoDay = z.iso.date('Enter a date as YYYY-MM-DD')
const RISK_GROUP_OF = { '1': 1, '2': 2, '3': 3, '4': 4 } as const satisfies Record<string, RiskGroup>
/** A native select gives text: '' until chosen, then the group as the API takes it (a number). */
const riskGroup = z.string().transform((value, ctx): RiskGroup => {
  const group = Object.entries(RISK_GROUP_OF).find(([text]) => text === value)?.[1]
  if (group !== undefined) return group
  ctx.addIssue({ code: 'custom', message: 'Choose a risk group' })
  return z.NEVER
})
const country = z.custom<CountryCode | ''>(isCountry, 'Choose a country')

/** What the check of a deposit found: the facts of the strain its acceptance creates. */
export const strainFactsSchema = z.object({
  taxon: z.custom<Taxon | null>().refine((value) => value !== null && value !== undefined, 'Choose a taxon'),
  identified_on: isoDay,
  identification_method: required('Enter how it was identified').max(200, 'Use at most 200 characters'),
  risk_group: riskGroup,
  animal_pathogenicity: choice(['unknown', 'none_known', 'pathogenic'], 'Choose one'),
  plant_pathogenicity: choice(['unknown', 'none_known', 'pathogenic'], 'Choose one'),
  isolation_source: z.string().trim().max(200, 'Use at most 200 characters'),
  country_of_origin: country,
  isolation_date: z
    .string()
    .trim()
    .regex(/^(\d{4}(-\d{2}(-\d{2})?)?)?$/, 'Use YYYY, YYYY-MM or YYYY-MM-DD'),
  restrictions: z.array(restrictionSchema).max(10, 'At most 10 restrictions'),
})
export type StrainFactsForm = z.input<typeof strainFactsSchema>
export type StrainFactsValues = z.output<typeof strainFactsSchema>

export const reasonSchema = required('Say why').max(2000, 'Use at most 2000 characters')

export const reclassifySchema = z.object({
  taxon: z.custom<Taxon | null>().refine((value) => value !== null && value !== undefined, 'Choose a taxon'),
  identified_on: isoDay,
  method: required('Enter how it was identified').max(200, 'Use at most 200 characters'),
  reason: reasonSchema,
})
export type ReclassifyForm = z.input<typeof reclassifySchema>

export const riskGroupSchema = z.object({ risk_group: riskGroup, reason: reasonSchema })
export type RiskGroupForm = z.input<typeof riskGroupSchema>
export type RiskGroupValues = z.output<typeof riskGroupSchema>

export const addRestrictionSchema = restrictionSchema.and(z.object({ reason: reasonSchema }))
export type AddRestrictionForm = z.input<typeof addRestrictionSchema>

export const endReasonSchema = z.object({ reason: reasonSchema })
export type EndReasonForm = z.input<typeof endReasonSchema>

/** The form's restriction as the API takes it: act only for dual-use, a category only for a GMO. */
export function restrictionBody(value: RestrictionForm) {
  return {
    kind: value.kind,
    reference: value.reference.trim(),
    act: value.kind === 'dual_use' ? value.act.trim() : '',
    gmo_category: value.kind === 'gmo' && value.gmo_category ? Number(value.gmo_category) : null,
  }
}
