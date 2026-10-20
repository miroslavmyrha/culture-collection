import { z } from 'zod'
import type { components } from '@/api/schema'
import { isCountry } from '@/lib/countries'
import { pageDefaults } from '@/lib/paging'

type Schemas = components['schemas']
export type Depositor = Schemas['DepositorOutput']
export type DepositorBrief = Schemas['DepositorBrief']
export type MtaTemplate = Schemas['MtaTemplateDetailOutput']
export type MtaTemplateRow = Schemas['MtaTemplateListOutput']
export type DepositRow = Schemas['DepositListOutput']
export type Deposit = Schemas['DepositDetailOutput']
export type Terms = Schemas['TermsOutput']
export type DepositStatus = Schemas['DepositStatus']
export type Condition = Schemas['Condition']
export type AbsScope = Schemas['AbsScope']
export type Use = Schemas['Use']
export type Decision = Schemas['Decision']
export type CountryCode = Schemas['CountryCode']
export type Role = Schemas['Role']
export type TermsBody = Schemas['TermsInputRequest']

/** Curators and managers handle depositors and deposits (deposits.view, deposits.manage). */
export const canHandleDeposits = (role: Role | undefined): boolean => role === 'curator' || role === 'manager'
/** Only managers publish an MTA version (deposits.manage_mta). The server decides; this hides. */
export const canPublishMta = (role: Role | undefined): boolean => role === 'manager'

export const STATUSES = ['received', 'checking', 'accepted', 'rejected'] as const satisfies readonly DepositStatus[]
export const STATUS_LABELS: Record<DepositStatus, string> = {
  received: 'Received',
  checking: 'Checking',
  accepted: 'Accepted',
  rejected: 'Rejected',
}
export const CONDITIONS = ['intact', 'damaged', 'other'] as const satisfies readonly Condition[]
export const CONDITION_LABELS: Record<Condition, string> = {
  intact: 'Intact',
  damaged: 'Container or packaging damaged',
  other: 'Other, see the note',
}
export const ABS_SCOPES = ['not_in_scope', 'in_scope', 'unknown'] as const satisfies readonly AbsScope[]
export const ABS_SCOPE_LABELS: Record<AbsScope, string> = {
  not_in_scope: 'Not in scope',
  in_scope: 'In scope',
  unknown: 'Unknown',
}
/** ADR 0008, D10, in the order the server lists them. To be confirmed with the curators. */
export const USES = [
  'research_noncommercial',
  'research_commercial',
  'teaching',
  'diagnostics',
  'production',
  'reference_qc',
  'patent_deposit_related',
  'redistribution',
] as const satisfies readonly Use[]
export const USE_LABELS: Record<Use, string> = {
  research_noncommercial: 'Non-commercial research',
  research_commercial: 'Commercial research',
  teaching: 'Teaching',
  diagnostics: 'Diagnostics',
  production: 'Production',
  reference_qc: 'Reference material and quality control',
  patent_deposit_related: 'Related to a patent deposit',
  redistribution: 'Redistribution to third parties',
}
export const DECISIONS = ['permit', 'deny', 'on_request'] as const satisfies readonly Decision[]
export const DECISION_LABELS: Record<Decision, string> = {
  permit: 'Permitted',
  deny: 'Not permitted',
  on_request: 'On request to the depositor',
}

export const options = <T extends string>(labels: Record<T, string>, values: readonly T[]) => values.map((value) => ({ value, label: labels[value] }))

/** Who a depositor is, also once the contact was erased. */
export const depositorName = (d: Pick<DepositorBrief, 'name' | 'erased'>) => (d.erased ? 'Erased contact' : d.name)
export const depositorLabel = (d: Pick<DepositorBrief, 'name' | 'erased' | 'institution'>) =>
  d.institution ? `${depositorName(d)}, ${d.institution}` : depositorName(d)
export const mtaLabel = (t: Pick<MtaTemplateRow, 'code' | 'version' | 'title'>) => `${t.code} version ${t.version}: ${t.title}`

// The lists' URL state. Defaults stay out of the URL; a bad value falls back to the default.
export const depositListDefaults = { ...pageDefaults, status: undefined, search: undefined }
export const depositListSearch = z.object({
  limit: z.number().int().min(1).max(200).default(pageDefaults.limit).catch(pageDefaults.limit),
  offset: z.number().int().min(0).default(pageDefaults.offset).catch(pageDefaults.offset),
  status: z.enum(STATUSES).optional().catch(undefined),
  search: z.string().trim().max(200).optional().catch(undefined),
})
export type DepositListParams = z.output<typeof depositListSearch>
export type DepositFilters = Omit<DepositListParams, 'limit' | 'offset'>

export const depositorListDefaults = { ...pageDefaults, search: undefined }
export const depositorListSearch = z.object({
  limit: z.number().int().min(1).max(200).default(pageDefaults.limit).catch(pageDefaults.limit),
  offset: z.number().int().min(0).default(pageDefaults.offset).catch(pageDefaults.offset),
  search: z.string().trim().max(200).optional().catch(undefined),
})
export type DepositorListParams = z.output<typeof depositorListSearch>

export const mtaNewSearch = z.object({ from: z.uuid().optional().catch(undefined) })

// Forms. Limits mirror the backend; the server still decides and its errors map back.
const required = (message: string) => z.string().trim().min(1, message)
const optionalText = (max: number) => z.string().trim().max(max, `Use at most ${max} characters`)
const isoDay = z.iso.date('Enter a date as YYYY-MM-DD')
/** A native select gives text: '' until chosen, then one of the values as the API takes it. */
const choice = <T extends string>(values: readonly T[], message: string) =>
  z.string().transform((value, ctx): T => {
    const found = values.find((v) => v === value)
    if (found !== undefined) return found
    ctx.addIssue({ code: 'custom', message })
    return z.NEVER
  })
const partialDate = z
  .string()
  .trim()
  .regex(/^(\d{4}(-\d{2}(-\d{2})?)?)?$/, 'Use YYYY, YYYY-MM or YYYY-MM-DD')

export const depositorSchema = z.object({
  name: required('Enter the name').max(200, 'Use at most 200 characters'),
  email: z.union([z.literal(''), z.email('Enter an e-mail address').max(254, 'Use at most 254 characters')]),
  postal_address: optionalText(1000),
  institution: optionalText(200),
})
export type DepositorForm = z.input<typeof depositorSchema>

export const mtaSchema = z.object({
  code: z
    .string()
    .trim()
    .regex(/^[A-Za-z0-9][A-Za-z0-9-]{0,19}$/, 'Use up to 20 letters, digits and hyphens, for example STD'),
  title: required('Enter the title').max(200, 'Use at most 200 characters'),
  text: z.string().refine((value) => value.trim().length > 0, 'Enter the text of the agreement').refine((value) => value.length <= 100_000, 'Use at most 100000 characters'),
})
export type MtaForm = z.input<typeof mtaSchema>

/** The terms of a deposit: a decision for every use, the MTA version, the ABS facts. */
export const termsSchema = z
  .object({
    mta: z.string(),
    abs_scope: choice(ABS_SCOPES, 'Choose the scope'),
    country_of_origin: z.custom<CountryCode | ''>(isCountry, 'Choose a country'),
    collection_date: partialDate,
    pic_reference: optionalText(200),
    mat_reference: optionalText(200),
    ircc: optionalText(100),
    permit_reference: optionalText(200),
    uses: z.array(z.object({ use: z.enum(USES), decision: choice(DECISIONS, 'Choose a decision') })).length(USES.length),
    /** The uses by a recipient the mutually agreed terms cover: in scope only. */
    mat_uses: z.array(z.enum(USES)),
  })
  .superRefine((value, ctx) => {
    // 511/2014, Art. 4(3): material in scope needs the IRCC or else the permit.
    if (value.abs_scope === 'in_scope' && !value.ircc.trim() && !value.permit_reference.trim())
      ctx.addIssue({ code: 'custom', path: ['ircc'], message: 'Material in scope needs an IRCC or a permit reference' })
  })
export type TermsForm = z.input<typeof termsSchema>
export type TermsValues = z.output<typeof termsSchema>

/** Every choice empty: the curator decides each one, nothing is preset. */
export const emptyTerms = (): TermsForm => ({
  mta: '',
  abs_scope: '',
  country_of_origin: '',
  collection_date: '',
  pic_reference: '',
  mat_reference: '',
  ircc: '',
  permit_reference: '',
  uses: USES.map((use) => ({ use, decision: '' })),
  mat_uses: [],
})

/** The terms as the API takes them: trimmed, the MTA by id or none. */
export function termsBody(values: TermsValues): TermsBody {
  return {
    mta: values.mta || null,
    abs_scope: values.abs_scope,
    country_of_origin: values.country_of_origin,
    collection_date: values.collection_date,
    pic_reference: values.pic_reference,
    mat_reference: values.mat_reference,
    ircc: values.ircc,
    permit_reference: values.permit_reference,
    uses: values.uses,
    // Boxes ticked before the scope changed stay in the form, not in the request.
    mat_uses: values.abs_scope === 'in_scope' ? USES.filter((use) => values.mat_uses.includes(use)) : [],
  }
}

export const receiveSchema = z
  .object({
    depositor: z.custom<Depositor | null>().refine((value) => value !== null && value !== undefined, 'Choose the depositor'),
    received_on: isoDay,
    condition: choice(CONDITIONS, 'Choose the condition'),
    condition_note: optionalText(2000),
    name_as_received: required('Enter the name as received').max(200, 'Use at most 200 characters'),
    depositor_passages: z
      .string()
      .trim()
      .regex(/^\d{0,5}$/, 'Enter a whole number, or leave it empty'),
    terms: termsSchema,
  })
  .superRefine((value, ctx) => {
    if (value.condition !== 'intact' && !value.condition_note)
      ctx.addIssue({ code: 'custom', path: ['condition_note'], message: 'Say what was wrong with it' })
  })
export type ReceiveForm = z.input<typeof receiveSchema>
export type ReceiveValues = z.output<typeof receiveSchema>

export const reasonSchema = required('Say why').max(2000, 'Use at most 2000 characters')
export const rejectSchema = z.object({ reason: reasonSchema })
export type RejectForm = z.input<typeof rejectSchema>
export const replaceTermsSchema = z.object({ terms: termsSchema, reason: reasonSchema })
export type ReplaceTermsForm = z.input<typeof replaceTermsSchema>
export type ReplaceTermsValues = z.output<typeof replaceTermsSchema>

/** A terms version as the form shows it, to start a new version from. */
export function termsForm(terms: Terms): TermsForm {
  const decided = new Map(terms.uses.map((u) => [u.use, u.decision]))
  return {
    mta: terms.mta?.public_id ?? '',
    abs_scope: terms.abs_scope,
    country_of_origin: isCountry(terms.country_of_origin) ? terms.country_of_origin : '',
    collection_date: terms.collection_date,
    pic_reference: terms.pic_reference,
    mat_reference: terms.mat_reference,
    ircc: terms.ircc,
    permit_reference: terms.permit_reference,
    uses: USES.map((use) => ({ use, decision: decided.get(use) ?? '' })),
    mat_uses: [...terms.mat_uses],
  }
}
