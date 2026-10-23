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
export type Shipment = Schemas['ShipmentOutput']
export type Preparation = Schemas['PreparationOutput']
export type TransportClass = Schemas['TransportClass']
export type ClassificationBasis = Schemas['ClassificationBasis']
export type PackingInstruction = Schemas['PackingInstruction']
export type Coolant = Schemas['Coolant']
export type ShipmentDocument = Schemas['ShipmentDocument']
export type ShipmentDocumentBrief = Schemas['ShipmentDocumentBrief']
export type ShipmentDocumentKind = Schemas['ShipmentDocumentKind']

/** Everyone in the lab reads requests (distribution.view): what is asked and what is reserved. */
export const canSeeRequests = (role: Role | undefined): boolean => role !== undefined
/** Curators and managers enter requests and requesters and decide (distribution.manage). */
export const canManageRequests = (role: Role | undefined): boolean => role === 'curator' || role === 'manager'
/** Only managers approve over a finding that needs one (distribution.approve_regulated). */
export const canApproveRegulated = (role: Role | undefined): boolean => role === 'manager'
/**
 * Curators and managers ship an approved request in one step. A regulated one leaves in two
 * (ADR 0009): one of them prepares the shipment, and another, neither the approver nor the
 * preparer, confirms it. The server refuses the one-step shipment with second_person_required.
 */
export const canShip = (request: Pick<RequestRow, 'status' | 'regulated'>, role: Role | undefined): boolean =>
  canManageRequests(role) && request.status === 'approved' && !request.regulated
export const canPrepare = (request: Pick<RequestRow, 'status' | 'regulated'>, role: Role | undefined): boolean =>
  canManageRequests(role) && request.status === 'approved' && request.regulated
/**
 * The documents of a shipment name the responsible person (#90): curators and managers open them
 * (distribution.view_requesters). Everyone in the lab sees which exist.
 */
export const canReadDocuments = (role: Role | undefined): boolean => role === 'curator' || role === 'manager'
export const DOCUMENT_KIND_LABELS: Record<ShipmentDocumentKind, string> = {
  delivery_note: 'Delivery note',
  abs_sheet: 'ABS information',
  register_entry: 'Register entry and handover protocol',
}
/** "Delivery note", or a per-line document with its strain: "ABS information for MYC 3". */
export const documentTitle = (d: Pick<ShipmentDocumentBrief, 'kind' | 'strain'>): string =>
  d.strain ? `${DOCUMENT_KIND_LABELS[d.kind]} for ${d.strain}` : DOCUMENT_KIND_LABELS[d.kind]
/** Enough of a SHA-256 to compare by eye; the document shows all of it. */
export const shortSha = (sha: string): string => sha.slice(0, 12)
export const documentDownloadHref = (labId: string, documentId: string): string =>
  `/api/v1/labs/${encodeURIComponent(labId)}/shipment-documents/${encodeURIComponent(documentId)}/download/`
/** The preparation a second person may confirm: the one not withdrawn, while the request waits. */
export const openPreparation = (request: Pick<Request, 'status' | 'preparations'>): Preparation | undefined =>
  request.status === 'awaiting_confirmation' ? request.preparations.find((p) => p.withdrawn_at === null) : undefined
/** Why the signed-in person may not confirm (the server says it; it refuses anyway). */
export const CONFIRM_REFUSALS: Record<NonNullable<Preparation['confirm_refusal']>, string> = {
  confirm_own_approval: 'You approved this request, so a different person confirms its shipment.',
  confirm_own_preparation: 'You prepared this shipment, so a different person confirms it.',
}

export const STATUSES = ['submitted', 'approved', 'awaiting_confirmation', 'shipped', 'rejected', 'cancelled'] as const satisfies readonly RequestStatus[]
export const STATUS_LABELS: Record<RequestStatus, string> = {
  submitted: 'Waiting for a decision',
  approved: 'Approved, vials reserved',
  awaiting_confirmation: 'Shipment prepared, waiting for a second person',
  shipped: 'Shipped',
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

/** The two classes this collection ships (ADR 0009): Category A and UN 3245 are refused. */
export const TRANSPORT_CLASSES = ['not_subject', 'un3373'] as const satisfies readonly TransportClass[]
export const TRANSPORT_CLASS_LABELS: Record<TransportClass, string> = {
  not_subject: 'Not subject to the dangerous goods rules (exempt)',
  un3373: 'UN 3373, Biological substance, Category B',
}
export const CLASSIFICATION_BASES = ['exempt_non_pathogenic', 'exempt_inactivated', 'indicative_list', 'professional_judgement'] as const satisfies readonly ClassificationBasis[]
export const BASIS_LABELS: Record<ClassificationBasis, string> = {
  exempt_non_pathogenic: 'Exempt: not pathogenic to humans or animals',
  exempt_inactivated: 'Exempt: neutralised or inactivated',
  indicative_list: 'Not on the indicative list of Category A',
  professional_judgement: 'Professional judgement',
}
/** The bases each class may rest on, as the server holds them (distribution.models.BASES). */
export const BASES: Record<TransportClass, readonly ClassificationBasis[]> = {
  not_subject: ['exempt_non_pathogenic', 'exempt_inactivated'],
  un3373: ['indicative_list', 'professional_judgement'],
}
export const PACKING_INSTRUCTIONS = ['p650', 'triple_packaging'] as const satisfies readonly PackingInstruction[]
export const PACKING_LABELS: Record<PackingInstruction, string> = { p650: 'P650', triple_packaging: 'Basic triple packaging' }
export const isTransportClass = (value: string): value is TransportClass => TRANSPORT_CLASSES.some((c) => c === value)
export const COOLANTS = ['dry_ice', 'cold_packs', 'liquid_nitrogen'] as const satisfies readonly Coolant[]
export const COOLANT_LABELS: Record<Coolant, string> = {
  dry_ice: 'Dry ice (UN 1845)',
  cold_packs: 'Ice or cold packs',
  liquid_nitrogen: 'Liquid nitrogen in a dry shipper',
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

/** As the server takes it: a digit or + first, then digits, spaces, ( ) and -, a digit last. */
const PHONE = /^[+0-9][0-9 ()-]{4,38}[0-9]$/
export const shipSchema = z
  .object({
    transport_class: choice(TRANSPORT_CLASSES, 'Choose the transport class'),
    classification_basis: choice(CLASSIFICATION_BASES, 'Choose the basis of the classification'),
    basis_note: optionalText(2000),
    packing_instruction: choice(PACKING_INSTRUCTIONS, 'Choose the packing'),
    coolant: z.union([z.literal(''), choice(COOLANTS, 'Choose the coolant')]),
    coolant_kg: z.union([z.literal(''), z.string().trim().regex(/^\d{1,4}([.,]\d{1,2})?$/, 'Enter kilograms, for example 2.5')]),
    responsible_name: required('Enter the responsible person').max(200, 'Use at most 200 characters'),
    responsible_phone: z.string().trim().max(40, 'Use at most 40 characters').regex(PHONE, 'Enter a phone number: digits, spaces, + ( ) and -'),
    carrier: required('Enter the carrier').max(200, 'Use at most 200 characters'),
    tracking_number: optionalText(100),
  })
  .superRefine((v, ctx) => {
    if (!BASES[v.transport_class].some((b) => b === v.classification_basis))
      ctx.addIssue({ code: 'custom', path: ['classification_basis'], message: 'Choose the basis of the classification' })
    if (v.classification_basis === 'professional_judgement' && !v.basis_note)
      ctx.addIssue({ code: 'custom', path: ['basis_note'], message: 'Say what the judgement rests on' })
    if (v.transport_class === 'un3373' && v.packing_instruction !== 'p650') ctx.addIssue({ code: 'custom', path: ['packing_instruction'], message: 'UN 3373 is packed to P650' })
    if (v.coolant === 'dry_ice' && !v.coolant_kg) ctx.addIssue({ code: 'custom', path: ['coolant_kg'], message: 'Give the quantity of dry ice: it is marked on the package' })
    if (v.coolant === '' && v.coolant_kg) ctx.addIssue({ code: 'custom', path: ['coolant'], message: 'Choose the coolant of this quantity' })
    if (v.coolant_kg && Number(v.coolant_kg.replace(',', '.')) <= 0) ctx.addIssue({ code: 'custom', path: ['coolant_kg'], message: 'Give more than 0 kg' })
  })
export type ShipForm = z.input<typeof shipSchema>
export type ShipValues = z.output<typeof shipSchema>

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
