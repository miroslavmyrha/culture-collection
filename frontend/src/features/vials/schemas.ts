import { z } from 'zod'
import type { components } from '@/api/schema'

type Schemas = components['schemas']
export type Passage = Schemas['PassageOutput']
export type Batch = Schemas['BatchOutput']
export type Vial = Schemas['VialOutput']
export type Location = Schemas['Location']
export type VialStatus = Schemas['VialStatus']
export type ManualStatus = Schemas['VialStatusInputStatusEnum']
export type Method = Schemas['PreservationMethod']
export type Purpose = Schemas['PurposeEnum']
export type BatchStatus = Schemas['BatchOutputStatusEnum']
export type Role = Schemas['Role']
export type Unit = Schemas['UnitOutput']
export type BoxGrid = Schemas['BoxGridOutput']
export type BoxPosition = Schemas['BoxPosition']
export type BoxVial = Schemas['BoxVial']
export type BatchCheck = Schemas['BatchCheckOutput']
export type CheckKind = Schemas['CheckKind']
export type CheckStage = Schemas['CheckStage']
export type CheckMethod = Schemas['CheckMethod']
export type CheckResult = Schemas['CheckResult']
export type CheckUnit = Schemas['CheckUnit']

/**
 * The Material tab's URL (#72): a page of the strain's vials, of all batches or of one. A
 * strain's vials may be many more than one answer holds (200), so the table pages and the count
 * of every vial shows. Defaults stay out of the URL; a bad value falls back to them.
 */
export const VIAL_PAGE = 50
export const vialPageDefaults = { limit: VIAL_PAGE, offset: 0, batch: undefined }
export const vialPageSearch = z.object({
  limit: z.number().int().min(1).max(200).default(VIAL_PAGE).catch(VIAL_PAGE),
  offset: z.number().int().min(0).default(0).catch(0),
  batch: z.uuid().optional().catch(undefined),
})
export type VialPage = z.output<typeof vialPageSearch>

/** Technicians and up do the bench work (vials.handle). The server decides; this only hides. */
export const canHandleVials = (role: Role | undefined): boolean => role === 'technician' || role === 'curator' || role === 'manager'

/** Curators and up release and hold batches (batches.release). The server decides; this only hides. */
export const canReleaseBatches = (role: Role | undefined): boolean => role === 'curator' || role === 'manager'

export const METHOD_LABELS: Record<Method, string> = {
  cryo_minus80: 'Frozen at -80 °C',
  cryo_ln2: 'Frozen in liquid nitrogen',
  lyophilised: 'Freeze-dried',
}
export const PURPOSE_LABELS: Record<Purpose, string> = { seed: 'Seed stock', distribution: 'Distribution stock' }
export const BATCH_STATUS_LABELS: Record<BatchStatus, string> = {
  pending_check: 'Pending check',
  released: 'Released',
  on_hold: 'On hold',
  exhausted: 'Exhausted',
}
export const VIAL_STATUS_LABELS: Record<VialStatus, string> = {
  available: 'Available',
  reserved: 'Reserved',
  consumed: 'Consumed',
  quarantined: 'Quarantined',
  to_destroy: 'To destroy',
  destroyed: 'Destroyed',
  lost: 'Lost',
  distributed: 'Distributed',
  entered_in_error: 'Entered in error',
}

/**
 * The states a person may set from each state (ADR 0008, D7, without reservation and dispatch,
 * which distribution records). The server checks the same edges; this only offers them.
 */
export const NEXT_STATES: Record<VialStatus, ManualStatus[]> = {
  available: ['quarantined', 'to_destroy', 'consumed', 'lost', 'entered_in_error'],
  reserved: ['to_destroy'],
  quarantined: ['available', 'to_destroy'],
  to_destroy: ['destroyed'],
  lost: ['available'],
  consumed: [],
  destroyed: [],
  distributed: [],
  entered_in_error: [],
}
/** A vial in one of these is in no box. */
export const OUT_OF_A_BOX: readonly VialStatus[] = ['consumed', 'destroyed', 'distributed', 'entered_in_error', 'lost']

export const nextStates = (vial: Vial): ManualStatus[] =>
  // Entered in error only while the state never changed (the server says so too).
  NEXT_STATES[vial.status].filter((s) => s !== 'entered_in_error' || vial.status_changed_at === null)

/** D6: rows as letters, columns as numbers, both from 1. */
export const rowLabel = (row: number) => String.fromCodePoint(64 + row)

export const sourceLabel = (p: Passage, passages: readonly Passage[]) => {
  if (p.source_kind === 'deposit') return 'As received'
  if (p.source_kind === 'vial') return p.source_vial_label ? `Revived from vial ${p.source_vial_label}` : 'Revived from a vial'
  const parent = passages.find((q) => q.public_id === p.source_passage)
  return parent ? `Subculture of passage ${parent.number}` : 'Subculture'
}

export type PassageNode = { passage: Passage; children: PassageNode[] }

/**
 * The passages as a tree from the original deposit (#19): passage 0 at the root, a subculture
 * under the passage it was grown from, a revival under the passage its vial's batch came from
 * (the server's `parent`). Children keep the order of the list, by number. A passage whose
 * parent is not in the list (the first page of a longer list) starts a tree of its own, so none
 * is dropped.
 */
export function passageTree(passages: readonly Passage[]): PassageNode[] {
  const nodes = new Map<string, PassageNode>(passages.map((passage) => [passage.public_id, { passage, children: [] }]))
  const roots: PassageNode[] = []
  for (const node of nodes.values()) {
    const parent = node.passage.parent === null ? undefined : nodes.get(node.passage.parent)
    if (parent && parent !== node) parent.children.push(node)
    else roots.push(node)
  }
  return roots
}

/** A box with the names of the units above it, for a select. */
export type BoxChoice = { public_id: string; label: string; rows: number; cols: number }

/** The active boxes of a lab's tree, each named by its path ("Freezer A / Rack 1 / Box 1"). */
export function boxChoices(units: readonly Unit[]): BoxChoice[] {
  const byId = new Map(units.map((u) => [u.public_id, u]))
  const path = (unit: Unit): string[] => {
    const parent = unit.parent ? byId.get(unit.parent) : undefined
    return parent ? [...path(parent), unit.name] : [unit.name]
  }
  return units
    .filter((u) => u.kind === 'box' && u.path_active && u.rows !== null && u.cols !== null)
    .map((u) => ({ public_id: u.public_id, label: path(u).join(' / '), rows: u.rows ?? 0, cols: u.cols ?? 0 }))
}

export const locationText = (l: Location) => `${l.path.join(' / ')}, ${l.label}`

// Forms. Limits mirror the backend; the server still decides and its errors map back.
const required = (message: string) => z.string().trim().min(1, message)
export const reasonSchema = required('Say why').max(2000, 'Use at most 2000 characters')
const today = () => new Date().toLocaleDateString('sv')

export const preserveSchema = z.object({
  passage: required('Choose the passage'),
  method: z.enum(['cryo_minus80', 'cryo_ln2', 'lyophilised'], 'Choose a method'),
  purpose: z.enum(['seed', 'distribution'], 'Choose a purpose'),
  cryoprotectant: z.string().trim().max(100, 'Use at most 100 characters'),
  preserved_on: z.iso.date('Enter a date as YYYY-MM-DD').refine((d) => d <= today(), 'This date is in the future'),
  vial_count: z
    .string()
    .trim()
    .min(1, 'Enter how many vials')
    .regex(/^\d+$/, 'Enter a whole number')
    .transform(Number)
    .refine((n) => n >= 1 && n <= 200, 'A batch has 1 to 200 vials'),
  box: z.string(),
})
export type PreserveForm = z.input<typeof preserveSchema>
export type PreserveValues = z.output<typeof preserveSchema>
export const emptyPreserve = (passage = ''): PreserveForm => ({
  passage,
  method: 'cryo_minus80',
  purpose: 'distribution',
  cryoprotectant: '',
  preserved_on: today(),
  vial_count: '',
  box: '',
})

const position = (message: string) => z.string().regex(/^\d+$/, message).transform(Number)
export const placeSchema = z.object({
  box: required('Choose the box'),
  row: position('Choose the row'),
  col: position('Choose the column'),
})
export type PlaceForm = z.input<typeof placeSchema>
export type PlaceValues = z.output<typeof placeSchema>

export const statusSchema = z.object({
  status: z.enum(['available', 'consumed', 'quarantined', 'to_destroy', 'destroyed', 'lost', 'entered_in_error'], 'Choose the new state'),
  reason: reasonSchema,
})
export type StatusForm = z.input<typeof statusSchema>

/** What the scanner sends or a person types to find a vial: its barcode or its label. */
export const findSchema = z.object({ code: required('Scan or type the label or barcode').max(200, 'Use at most 200 characters') })
export type FindForm = z.input<typeof findSchema>

// Checks of a batch (#17, ADR 0008, D16). The vocabularies mirror lineage.models; the server
// checks every rule again.
export const CHECK_KINDS: readonly CheckKind[] = ['identity', 'purity', 'viability']
export const KIND_LABELS: Record<CheckKind, string> = { identity: 'Identity', purity: 'Purity', viability: 'Viability' }
export const STAGE_LABELS: Record<CheckStage, string> = {
  after_preservation: 'After preservation',
  periodic: 'Periodic',
  before_dispatch: 'Before dispatch',
}
export const RESULT_LABELS: Record<CheckResult, string> = { pass: 'Passed', reduced: 'Reduced', fail: 'Failed' }
export const CHECK_METHOD_LABELS: Record<CheckMethod, string> = {
  morphology: 'Colony and cell morphology',
  biochemical: 'Biochemical profile',
  maldi_tof: 'MALDI-TOF mass spectrometry',
  sequencing: 'Gene sequencing',
  streak_plate: 'Streak plate',
  microscopy: 'Microscopy',
  growth: 'Growth after revival',
  plate_count: 'Plate count',
  live_dead_stain: 'Live and dead staining',
  other: 'Other',
}
export const METHODS_BY_KIND: Record<CheckKind, readonly CheckMethod[]> = {
  identity: ['morphology', 'biochemical', 'maldi_tof', 'sequencing', 'other'],
  purity: ['streak_plate', 'microscopy', 'other'],
  viability: ['growth', 'plate_count', 'live_dead_stain', 'other'],
}
export const UNIT_LABELS: Record<CheckUnit, string> = { cfu_per_ml: 'CFU/mL', percent: '%' }

/** Reduced counts as passed for a release; its check says what was seen. */
const PASSING: readonly (CheckResult | null)[] = ['pass', 'reduced']

/** The kinds whose latest valid check did not pass: what stands between the batch and a release. */
export const notPassed = (batch: Batch): CheckKind[] => CHECK_KINDS.filter((kind) => !PASSING.includes(batch.latest_checks[kind]))

/** identity; identity and purity; identity, purity and viability. */
export function kindsText(kinds: readonly CheckKind[]): string {
  const names = kinds.map((kind) => KIND_LABELS[kind].toLowerCase())
  return names.length <= 1 ? (names[0] ?? '') : `${names.slice(0, -1).join(', ')} and ${names.at(-1) ?? ''}`
}

/** Why the batch has its status, in a sentence: what it waits for, or the recorded reason. */
export function batchStatusReason(batch: Batch): string {
  if (batch.status === 'pending_check') {
    const missing = notPassed(batch)
    if (missing.length === 0) return 'All checks passed. A curator releases it.'
    return `Waiting for a passed ${kindsText(missing)} check.`
  }
  return batch.status_reason
}

/** A batch a curator may release now: pending or on hold, and its latest checks passed. */
export const mayRelease = (batch: Batch): boolean => (batch.status === 'pending_check' || batch.status === 'on_hold') && notPassed(batch).length === 0
/** A batch a curator may hold now. */
export const mayHold = (batch: Batch): boolean => batch.status === 'pending_check' || batch.status === 'released'

/** How a check reads in the history: method and detail, value and unit, the vial, the person. */
export function checkDetails(check: BatchCheck): string {
  const method = check.method_detail ? `${CHECK_METHOD_LABELS[check.method]} (${check.method_detail})` : CHECK_METHOD_LABELS[check.method]
  const parts = [method]
  if (check.value !== null && check.unit !== '') parts.push(`${formatValue(check.value)} ${UNIT_LABELS[check.unit]}`)
  if (check.vial_label) parts.push(`vial ${check.vial_label}`)
  parts.push(STAGE_LABELS[check.stage].toLowerCase(), `by ${check.performed_by}`)
  return parts.join(', ')
}

/** A stored decimal without its trailing zeros: "250000000.0000" reads 250000000, "12.5000" 12.5. */
export const formatValue = (value: string) => (value.includes('.') ? value.replace(/\.?0+$/, '') : value)

const NUMBER = /^\d+(\.\d{1,4})?([eE]\d{1,2})?$/

export const checkSchema = z
  .object({
    kind: z.enum(['identity', 'purity', 'viability'], 'Choose the kind'),
    stage: z.enum(['after_preservation', 'periodic', 'before_dispatch'], 'Choose the stage'),
    checked_on: z.iso.date('Enter a date as YYYY-MM-DD').refine((d) => d <= today(), 'This date is in the future'),
    method: z.enum(['morphology', 'biochemical', 'maldi_tof', 'sequencing', 'streak_plate', 'microscopy', 'growth', 'plate_count', 'live_dead_stain', 'other'], 'Choose the method'),
    method_detail: z.string().trim().max(200, 'Use at most 200 characters'),
    result: z.enum(['pass', 'reduced', 'fail'], 'Choose the result'),
    value: z.string().trim().refine((v) => v === '' || NUMBER.test(v), 'Enter a number, as 12.5 or 2.1e8'),
    unit: z.enum(['', 'cfu_per_ml', 'percent']),
    vial: z.string(),
    note: z.string().trim().max(2000, 'Use at most 2000 characters'),
  })
  .superRefine((form, ctx) => {
    if (!METHODS_BY_KIND[form.kind].includes(form.method)) ctx.addIssue({ code: 'custom', path: ['method'], message: 'Choose a method of this kind' })
    if (form.method === 'other' && form.method_detail === '') ctx.addIssue({ code: 'custom', path: ['method_detail'], message: 'Describe the method' })
    if (form.value !== '' && form.unit === '') ctx.addIssue({ code: 'custom', path: ['unit'], message: 'Choose the unit of the value' })
    if (form.value === '' && form.unit !== '') ctx.addIssue({ code: 'custom', path: ['value'], message: 'Enter the value, or no unit' })
    if (form.unit === 'percent' && NUMBER.test(form.value) && Number(form.value) > 100) ctx.addIssue({ code: 'custom', path: ['value'], message: 'A percentage is at most 100' })
    if (form.result === 'reduced' && form.note === '') ctx.addIssue({ code: 'custom', path: ['note'], message: 'Say what was reduced' })
  })
export type CheckForm = z.input<typeof checkSchema>
export type CheckValues = z.output<typeof checkSchema>

/** A new check of the batch: the first kind it still waits for, after preservation if it has none yet. */
export function emptyCheck(batch: Batch): CheckForm {
  const kind = notPassed(batch)[0] ?? 'viability'
  const checked = CHECK_KINDS.some((k) => batch.latest_checks[k] !== null)
  return {
    kind,
    stage: checked ? 'periodic' : 'after_preservation',
    checked_on: today(),
    method: METHODS_BY_KIND[kind][0] ?? 'other',
    method_detail: '',
    result: 'pass',
    value: '',
    unit: '',
    vial: '',
    note: '',
  }
}

/** A release, a hold or a check entered in error: why, in a sentence. */
export const decisionSchema = z.object({ reason: reasonSchema })
export type DecisionForm = z.input<typeof decisionSchema>
