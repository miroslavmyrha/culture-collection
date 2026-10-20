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

/** Technicians and up do the bench work (vials.handle). The server decides; this only hides. */
export const canHandleVials = (role: Role | undefined): boolean => role === 'technician' || role === 'curator' || role === 'manager'

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
  if (p.source_kind === 'vial') return 'Revived from a vial'
  const parent = passages.find((q) => q.public_id === p.source_passage)
  return parent ? `Subculture of passage ${parent.number}` : 'Subculture'
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
