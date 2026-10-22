import { z } from 'zod'
import type { components } from '@/api/schema'
import { isCountry } from '@/lib/countries'
import { pageDefaults } from '@/lib/paging'

type Schemas = components['schemas']
export type RequestRow = Schemas['RequestListOutput']
export type Request = Schemas['RequestDetailOutput']
export type Line = Schemas['LineOutput']
export type Finding = Schemas['Finding']
export type Acceptance = Schemas['AcceptanceOutput']
export type Requester = Schemas['RequesterOutput']
export type Permit = Schemas['PermitOutput']
export type RequestStatus = Schemas['RequestStatus']
export type PermitKind = Schemas['PermitKind']
export type LegalForm = Schemas['LegalForm']
export type SignerRole = Schemas['SignerRole']
export type Use = Schemas['Use']
export type CountryCode = Schemas['CountryCode']
export type Role = Schemas['Role']
export type StrainChoice = Schemas['StrainListOutput']

/** Everyone in the lab reads requests (distribution.view): what is asked and what is reserved. */
export const canSeeRequests = (role: Role | undefined): boolean => role !== undefined
/** Curators and managers enter requests and requesters and decide (distribution.manage). */
export const canManageRequests = (role: Role | undefined): boolean => role === 'curator' || role === 'manager'
/** Only managers approve over a finding that needs one (distribution.approve_regulated). */
export const canApproveRegulated = (role: Role | undefined): boolean => role === 'manager'

export const STATUSES = ['submitted', 'approved', 'rejected', 'cancelled'] as const satisfies readonly RequestStatus[]
export const STATUS_LABELS: Record<RequestStatus, string> = {
  submitted: 'Waiting for a decision',
  approved: 'Approved, vials reserved',
  rejected: 'Rejected',
  cancelled: 'Cancelled',
}
/** ADR 0008, D10, in the order the server lists them. */
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
export const LEGAL_FORMS = ['legal_person', 'business'] as const satisfies readonly LegalForm[]
export const LEGAL_FORM_LABELS: Record<LegalForm, string> = {
  legal_person: 'Legal person (an institution or a company)',
  business: 'Natural person licensed to do business',
}
export const PERMIT_KINDS = [
  'sujb_vrat',
  'sujb_rat_notice',
  'sujb_exception',
  'plant_health_loa',
  'gmo_contained_use',
  'pathogen_work_permit',
] as const satisfies readonly PermitKind[]
export const PERMIT_KIND_LABELS: Record<PermitKind, string> = {
  sujb_vrat: 'SÚJB permit for highly risky agents (VRAT)',
  sujb_rat_notice: 'Notice to SÚJB of handling risky agents (RAT)',
  sujb_exception: 'SÚJB decision allowing a VRAT to a non-holder',
  plant_health_loa: 'Letter of Authority for a quarantine pest',
  gmo_contained_use: 'Authorisation for contained use of GMOs',
  pathogen_work_permit: 'Permit to work with pathogens',
}
/** The kinds that name the agents or pests they cover: the server reads the strain's name there. */
export const NAMES_AGENTS: readonly PermitKind[] = ['sujb_vrat', 'sujb_exception', 'plant_health_loa']
export const SIGNER_ROLES = ['responsible_scientist', 'head_of_institution', 'authorised_representative'] as const satisfies readonly SignerRole[]
export const SIGNER_ROLE_LABELS: Record<SignerRole, string> = {
  responsible_scientist: 'Responsible scientist',
  head_of_institution: 'Head of the institution or department',
  authorised_representative: 'Authorised representative',
}

export const options = <T extends string>(labels: Record<T, string>, values: readonly T[]) => values.map((value) => ({ value, label: labels[value] }))

/** Who the requester is, also once the contact was erased. */
export const scientistName = (r: Pick<Requester, 'name' | 'erased'>) => (r.erased ? 'Erased contact' : r.name)

// The lists' URL state. Defaults stay out of the URL; a bad value falls back to the default.
export const requestListDefaults = { ...pageDefaults, status: undefined, search: undefined }
export const requestListSearch = z.object({
  limit: z.number().int().min(1).max(200).default(pageDefaults.limit).catch(pageDefaults.limit),
  offset: z.number().int().min(0).default(pageDefaults.offset).catch(pageDefaults.offset),
  status: z.enum(STATUSES).optional().catch(undefined),
  search: z.string().trim().max(200).optional().catch(undefined),
})
export type RequestListParams = z.output<typeof requestListSearch>
export type RequestFilters = Omit<RequestListParams, 'limit' | 'offset'>

export const requesterListDefaults = { ...pageDefaults, search: undefined }
export const requesterListSearch = z.object({
  limit: z.number().int().min(1).max(200).default(pageDefaults.limit).catch(pageDefaults.limit),
  offset: z.number().int().min(0).default(pageDefaults.offset).catch(pageDefaults.offset),
  search: z.string().trim().max(200).optional().catch(undefined),
})
export type RequesterListParams = z.output<typeof requesterListSearch>

// Forms. Limits mirror the backend; the server still decides and its errors map back.
const required = (message: string) => z.string().trim().min(1, message)
const optionalText = (max: number) => z.string().trim().max(max, `Use at most ${max} characters`)
const isoDay = z.iso.date('Enter a date as YYYY-MM-DD')
const optionalDay = z.union([z.literal(''), z.iso.date('Enter a date as YYYY-MM-DD')])
/** A native select gives text: '' until chosen, then one of the values as the API takes it. */
const choice = <T extends string>(values: readonly T[], message: string) =>
  z.string().transform((value, ctx): T => {
    const found = values.find((v) => v === value)
    if (found !== undefined) return found
    ctx.addIssue({ code: 'custom', message })
    return z.NEVER
  })
/** A file input registered with react-hook-form gives a FileList: its first file, or none. */
const fileOf = (message: string) =>
  z
    .custom<FileList | null>((v) => v === null || v instanceof FileList)
    .transform((v, ctx): File => {
      const file = v?.[0]
      if (file !== undefined) return file
      ctx.addIssue({ code: 'custom', message })
      return z.NEVER
    })
const wholeNumber = (min: number, max: number, message: string) =>
  z
    .string()
    .trim()
    .regex(/^\d+$/, message)
    .transform(Number)
    .refine((n) => n >= min && n <= max, message)
const optionalNumber = (min: number, max: number, message: string) =>
  z.union([z.literal(''), z.string().trim().regex(/^\d+$/, message).refine((v) => Number(v) >= min && Number(v) <= max, message)])

export const reasonSchema = required('Say why').max(2000, 'Use at most 2000 characters')
export const decisionSchema = z.object({ reason: reasonSchema })
export type DecisionForm = z.input<typeof decisionSchema>
export const approveSchema = z.object({ reason: optionalText(2000) })
export type ApproveForm = z.input<typeof approveSchema>

export const requesterSchema = z.object({
  institution: required('Enter the institution').max(200, 'Use at most 200 characters'),
  legal_form: choice(LEGAL_FORMS, 'Choose the legal form'),
  registration_number: optionalText(40),
  country: z.custom<CountryCode | ''>(isCountry, 'Choose a country').refine((v) => v !== '', 'Choose a country'),
  lab_evidence: required('Say how the microbiology laboratory was confirmed').max(2000, 'Use at most 2000 characters'),
  lab_confirmed_on: isoDay,
  name: required('Enter the name of the responsible scientist').max(200, 'Use at most 200 characters'),
  email: z.union([z.literal(''), z.email('Enter an e-mail address').max(254, 'Use at most 254 characters')]),
  postal_address: required('Enter the delivery address of the laboratory').max(1000, 'Use at most 1000 characters'),
})
export type RequesterForm = z.input<typeof requesterSchema>
export type RequesterValues = z.output<typeof requesterSchema>

export const permitSchema = z
  .object({
    kind: choice(PERMIT_KINDS, 'Choose the kind'),
    issuer: required('Enter the issuing authority').max(200, 'Use at most 200 characters'),
    issuer_country: z.custom<CountryCode | ''>(isCountry, 'Choose a country').refine((v) => v !== '', 'Choose a country'),
    reference: required('Enter the reference').max(200, 'Use at most 200 characters'),
    valid_from: isoDay,
    expires_on: optionalDay,
    covers: optionalText(2000),
    quantity_allowed: optionalNumber(1, 100000, 'Enter a whole number of 1 or more'),
    sendings_allowed: optionalNumber(1, 1000, 'Enter a whole number of 1 or more'),
    gmo_category: optionalNumber(1, 4, 'Enter a category from 1 to 4'),
    risk_group: optionalNumber(1, 4, 'Enter a risk group from 1 to 4'),
    file: fileOf('Choose the file of the document'),
  })
  .superRefine((v, ctx) => {
    if (NAMES_AGENTS.some((k) => k === v.kind) && !v.covers) ctx.addIssue({ code: 'custom', path: ['covers'], message: 'Write the agents or pests it names, as on the document' })
    if (v.kind === 'plant_health_loa' && !v.quantity_allowed) ctx.addIssue({ code: 'custom', path: ['quantity_allowed'], message: 'Enter the quantity the letter allows' })
    if (v.kind === 'plant_health_loa' && !v.sendings_allowed) ctx.addIssue({ code: 'custom', path: ['sendings_allowed'], message: 'Enter the number of sendings' })
    if (v.kind === 'gmo_contained_use' && !v.gmo_category) ctx.addIssue({ code: 'custom', path: ['gmo_category'], message: 'Enter the category' })
    if (v.kind === 'pathogen_work_permit' && !v.risk_group) ctx.addIssue({ code: 'custom', path: ['risk_group'], message: 'Enter the risk group it covers' })
  })
export type PermitForm = z.input<typeof permitSchema>
export type PermitValues = z.output<typeof permitSchema>

export const endPermitSchema = z.object({ ended_on: isoDay, reason: reasonSchema })
export type EndPermitForm = z.input<typeof endPermitSchema>

export const acceptanceSchema = z.object({
  mta: required('Choose the MTA version'),
  signer_name: required('Enter who signed').max(200, 'Use at most 200 characters'),
  signer_email: z.union([z.literal(''), z.email('Enter an e-mail address').max(254, 'Use at most 254 characters')]),
  signer_role: choice(SIGNER_ROLES, 'Choose the signer’s role'),
  authorised_signatory: z.boolean(),
  accepted_on: isoDay,
  file: fileOf('Choose the signed copy'),
})
export type AcceptanceForm = z.input<typeof acceptanceSchema>
export type AcceptanceValues = z.output<typeof acceptanceSchema>

const lineSchema = z.object({
  strain: z.custom<StrainChoice | null>().refine((v) => v !== null && v !== undefined, 'Choose the strain'),
  quantity: wholeNumber(1, 50, 'Ask for 1 to 50 vials'),
})
export const requestSchema = z
  .object({
    requester: required('Choose the requester'),
    use: choice(USES, 'Choose the use'),
    end_use: required('Say what the recipient will use it for').max(2000, 'Use at most 2000 characters'),
    containment_level: choice(['1', '2', '3', '4'] as const, 'Choose the containment level'),
    lines: z.array(lineSchema).min(1, 'Add a strain').max(20, 'A request has at most 20 strains'),
  })
  .superRefine((v, ctx) => {
    const seen = new Set<string>()
    v.lines.forEach((line, i) => {
      const id = line.strain?.public_id
      if (id === undefined) return
      if (seen.has(id)) ctx.addIssue({ code: 'custom', path: ['lines', i, 'strain'], message: 'This strain is listed twice' })
      seen.add(id)
    })
  })
export type RequestForm = z.input<typeof requestSchema>
export type RequestValues = z.output<typeof requestSchema>

/** A request's number as people say it. */
export const requestLabel = (r: Pick<RequestRow, 'number'>) => `Request ${r.number}`
