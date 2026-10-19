import { z } from 'zod'
import type { components } from '@/api/schema'

type Schemas = components['schemas']
export type UnitRow = Schemas['UnitOutput']
export type Unit = Schemas['UnitDetailOutput']
export type UnitKind = Schemas['UnitKind']
export type UnitStatus = Schemas['UnitStatus']
export type BoxType = Schemas['BoxTypeOutput']
type Role = Schemas['Role']

/** Curators and managers build the storage tree (storage.manage). The server decides; this only hides. */
export const canManageStorage = (role: Role | undefined): boolean => role === 'curator' || role === 'manager'

export const KIND_LABELS: Record<UnitKind, string> = { freezer: 'Freezer', ln2_tank: 'LN2 tank', rack: 'Rack', box: 'Box' }
/** The kind inside a sentence: "a rack in slot 2". */
export const KIND_WORDS: Record<UnitKind, string> = { freezer: 'freezer', ln2_tank: 'LN2 tank', rack: 'rack', box: 'box' }
export const STATUS_LABELS: Record<UnitStatus, string> = { active: 'Active', out_of_service: 'Out of service', retired: 'Retired' }

/**
 * Which kind may hold which, as the server's kind spec says (storage.models.KIND_SPEC). Used
 * to offer only what the server accepts; it still decides.
 */
export const HOLDS: Record<UnitKind, readonly UnitKind[]> = { freezer: ['rack', 'box'], ln2_tank: ['rack', 'box'], rack: ['box'], box: [] }
export const ROOT_KINDS = ['freezer', 'ln2_tank'] as const satisfies readonly UnitKind[]
export const isRoot = (kind: UnitKind) => (ROOT_KINDS as readonly UnitKind[]).includes(kind)

/** ADR 0008, D6: rows are letters and columns numbers, both from 1, so row 1, column 1 is A1. */
export const positionLabel = (row: number, col: number) => `${String.fromCharCode(64 + row)}${col}`

/** "9 x 9, A1 to I9". */
export const sizeLabel = (rows: number, cols: number) => `${rows} x ${cols}, ${positionLabel(1, 1)} to ${positionLabel(rows, cols)}`

/** "-80 °C" with a space that never breaks, so the number keeps its unit on a narrow screen. */
export const degrees = (celsius: number) => `${celsius}\u00a0°C`

type Summarised = Pick<UnitRow, 'kind' | 'slot' | 'rows' | 'cols' | 'status' | 'temperature_c'>

/** What a unit is, in the words that follow its name: "box in slot 1, 9 x 9". */
export function unitSummary(unit: Summarised): string {
  const kind = KIND_WORDS[unit.kind]
  const parts = [unit.slot === null ? kind : `${kind} in slot ${unit.slot}`]
  if (unit.rows !== null && unit.cols !== null) parts.push(`${unit.rows} x ${unit.cols}`)
  if (unit.temperature_c !== null) parts.push(degrees(unit.temperature_c))
  if (unit.status !== 'active') parts.push(STATUS_LABELS[unit.status].toLowerCase())
  return parts.join(', ')
}

// Forms. Limits mirror the backend; the server still decides and its errors map back.
const required = (message: string) => z.string().trim().min(1, message)
/** A number field is text: '' for none, else a whole number within the limits. */
const wholeNumber = (min: number, max: number, message: string) =>
  z
    .string()
    .trim()
    .refine((value) => value === '' || (/^-?\d+$/.test(value) && Number(value) >= min && Number(value) <= max), message)
const toNumber = (value: string) => (value.trim() === '' ? null : Number(value))
export const RISK_GROUP_CHOICES = ['1', '2', '3', '4'] as const
type RiskGroupChoice = (typeof RISK_GROUP_CHOICES)[number]
const CAPS = { '1': 1, '2': 2, '3': 3, '4': 4 } as const satisfies Record<RiskGroupChoice, Schemas['RiskGroup']>
const isChoice = (value: string): value is RiskGroupChoice => (RISK_GROUP_CHOICES as readonly string[]).includes(value)
const cap = (value: string): Schemas['RiskGroup'] | null => (isChoice(value) ? CAPS[value] : null)

const fieldShape = {
  name: required('Enter a name').max(100, 'Use at most 100 characters'),
  barcode: z
    .string()
    .trim()
    .max(64, 'Use at most 64 characters')
    .refine((value) => !/\s/.test(value), 'A barcode has no spaces'),
  temperature_c: wholeNumber(-273, 100, 'Enter whole degrees from -273 to 100'),
  max_risk_group: z.enum(['', ...RISK_GROUP_CHOICES], 'Choose a risk group'),
  box_type: z.string(),
}

/** A root states its cap, a box its type: the same rules as the server, before the request. */
function kindRules(kind: UnitKind, value: { max_risk_group: string; box_type: string }, ctx: z.RefinementCtx) {
  if (isRoot(kind) && value.max_risk_group === '') ctx.addIssue({ code: 'custom', path: ['max_risk_group'], message: 'A freezer or tank states the highest risk group it may hold' })
  if (kind === 'box' && value.box_type === '') ctx.addIssue({ code: 'custom', path: ['box_type'], message: 'Choose the box type' })
}

export const createUnitSchema = z
  .object({
    kind: z.enum(['freezer', 'ln2_tank', 'rack', 'box'], 'Choose a kind'),
    ...fieldShape,
    slot: wholeNumber(1, 32767, 'Enter a slot number from 1'),
  })
  .superRefine((value, ctx) => kindRules(value.kind, value, ctx))
export type CreateUnitForm = z.input<typeof createUnitSchema>

export const editUnitSchema = (kind: UnitKind) => z.object(fieldShape).superRefine((value, ctx) => kindRules(kind, value, ctx))
export type EditUnitForm = z.input<ReturnType<typeof editUnitSchema>>

export const moveUnitSchema = z.object({
  parent: required('Choose where it goes'),
  slot: wholeNumber(1, 32767, 'Enter a slot number from 1'),
})
export type MoveUnitForm = z.input<typeof moveUnitSchema>

export const reasonSchema = required('Say why').max(2000, 'Use at most 2000 characters')
export const statusSchema = z.object({ reason: reasonSchema })
export type StatusForm = z.input<typeof statusSchema>

/** The edit form's values as the API takes them: a box type only for a box. */
export function fieldsBody(kind: UnitKind, value: EditUnitForm) {
  return {
    name: value.name.trim(),
    barcode: value.barcode.trim(),
    temperature_c: toNumber(value.temperature_c),
    max_risk_group: cap(value.max_risk_group),
    box_type: kind === 'box' && value.box_type ? value.box_type : null,
  }
}

export function createBody(value: CreateUnitForm, parent: string | null) {
  return { kind: value.kind, parent, slot: parent === null ? null : toNumber(value.slot), ...fieldsBody(value.kind, value) }
}

export function moveBody(value: MoveUnitForm) {
  return { parent: value.parent, slot: toNumber(value.slot) }
}

const choiceOf = (group: number): RiskGroupChoice | '' => {
  const text = String(group)
  return isChoice(text) ? text : ''
}

export const emptyFields = (unit?: Pick<UnitRow, 'name' | 'barcode' | 'temperature_c' | 'max_risk_group' | 'box_type'>): EditUnitForm => ({
  name: unit?.name ?? '',
  barcode: unit?.barcode ?? '',
  temperature_c: unit?.temperature_c === null || unit?.temperature_c === undefined ? '' : String(unit.temperature_c),
  max_risk_group: unit?.max_risk_group ? choiceOf(unit.max_risk_group) : '',
  box_type: unit?.box_type?.public_id ?? '',
})
