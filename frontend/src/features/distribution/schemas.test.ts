import userEvent from '@testing-library/user-event'
import { beforeAll, describe, expect, it } from 'vitest'
import { permitSchema, shipSchema } from './schemas'

// jsdom has no DataTransfer: a FileList comes from a file input that a user filled.
let files: FileList | null = null
beforeAll(async () => {
  const input = document.createElement('input')
  input.type = 'file'
  document.body.append(input)
  await userEvent.setup().upload(input, new File(['%PDF-1.4'], 'permit.pdf', { type: 'application/pdf' }))
  files = input.files
  input.remove()
})
const file = () => files
const permit = (overrides: Record<string, unknown> = {}) => ({
  kind: 'sujb_rat_notice',
  issuer: 'SÚJB',
  issuer_country: 'CZ',
  reference: 'DEV/1',
  valid_from: '2026-01-01',
  expires_on: '',
  covers: '',
  endorsement_reference: '',
  endorsed_on: '',
  quantity_allowed: '',
  sendings_allowed: '',
  gmo_category: '',
  risk_group: '',
  file: file(),
  ...overrides,
})
const issues = (value: unknown) => {
  const result = permitSchema.safeParse(value)
  return result.success ? [] : result.error.issues.map((issue) => issue.path.join('.'))
}

describe('the permit form', () => {
  it('asks a VRAT permit, a RAT notice, an exception and a Letter of Authority for what they name, as on the document', () => {
    for (const kind of ['sujb_vrat', 'sujb_rat_notice', 'sujb_exception', 'plant_health_loa']) expect(issues(permit({ kind }))).toContain('covers')
    expect(issues(permit({ kind: 'sujb_vrat', covers: 'Mockia vulgaris' }))).toEqual([])
    expect(issues(permit({ covers: 'Mockia vulgaris' }))).toEqual([])
  })

  it('asks a letter for its quantity and sendings, a GMO authorisation for its category, a work permit for its risk group', () => {
    expect(issues(permit({ kind: 'plant_health_loa', covers: 'Mockia vulgaris' }))).toEqual(['quantity_allowed', 'sendings_allowed'])
    expect(issues(permit({ kind: 'gmo_contained_use' }))).toEqual(['gmo_category'])
    expect(issues(permit({ kind: 'pathogen_work_permit' }))).toEqual(['risk_group'])
  })

  it('asks a Letter of Authority for the endorsement with its day, or for neither', () => {
    const letter = { kind: 'plant_health_loa', covers: 'Mockia vulgaris', quantity_allowed: '4', sendings_allowed: '2' }
    expect(issues(permit(letter))).toEqual([])
    expect(issues(permit({ ...letter, endorsement_reference: 'ÚKZÚZ/E/1' }))).toEqual(['endorsed_on'])
    expect(issues(permit({ ...letter, endorsed_on: '2026-01-02' }))).toEqual(['endorsement_reference'])
    expect(issues(permit({ ...letter, endorsement_reference: 'ÚKZÚZ/E/1', endorsed_on: '2026-01-02' }))).toEqual([])
  })

  it('needs the file', () => {
    expect(issues(permit({ file: null }))).toEqual(['file'])
  })
})

const shipment = (overrides: Record<string, unknown> = {}) => ({
  transport_class: 'not_subject',
  classification_basis: 'exempt_non_pathogenic',
  basis_note: '',
  packing_instruction: 'triple_packaging',
  coolant: '',
  coolant_kg: '',
  responsible_name: 'Jan Odpovědný',
  responsible_phone: '+420 555 000 111',
  carrier: 'Example Courier',
  tracking_number: '',
  ...overrides,
})
const shipIssues = (value: unknown) => {
  const result = shipSchema.safeParse(value)
  return result.success ? [] : result.error.issues.map((issue) => `${issue.path.join('.')}: ${issue.message}`)
}

describe('the shipment form', () => {
  it('accepts an exempt shipment with no coolant', () => {
    expect(shipIssues(shipment())).toEqual([])
  })

  it('refuses a basis the class does not rest on', () => {
    expect(shipIssues(shipment({ classification_basis: 'indicative_list' }))).toEqual(['classification_basis: Choose the basis of the classification'])
    expect(shipIssues(shipment({ transport_class: 'un3245', classification_basis: 'gmo_not_infectious', packing_instruction: 'p650' }))).toEqual([])
  })

  it('asks a professional judgement for what it rests on', () => {
    const judged = { transport_class: 'un3373', classification_basis: 'professional_judgement', packing_instruction: 'p650' }
    expect(shipIssues(shipment(judged))).toEqual(['basis_note: Say what the judgement rests on'])
    expect(shipIssues(shipment({ ...judged, basis_note: 'Tested negative.' }))).toEqual([])
  })

  it('packs UN 3373 to P650', () => {
    expect(shipIssues(shipment({ transport_class: 'un3373', classification_basis: 'indicative_list' }))).toEqual(['packing_instruction: UN 3373 is packed to P650'])
  })

  it('asks dry ice for its quantity and a quantity for its coolant', () => {
    expect(shipIssues(shipment({ coolant: 'dry_ice' }))).toEqual(['coolant_kg: Give the quantity of dry ice: it is marked on the package'])
    expect(shipIssues(shipment({ coolant: 'dry_ice', coolant_kg: '2,5' }))).toEqual([])
    expect(shipIssues(shipment({ coolant_kg: '2' }))).toEqual(['coolant: Choose the coolant of this quantity'])
  })

  it('refuses zero kilograms', () => {
    expect(shipIssues(shipment({ coolant: 'cold_packs', coolant_kg: '0' }))).toEqual(['coolant_kg: Give more than 0 kg'])
  })

  it('reports the issues in the order of the rules', () => {
    expect(shipIssues(shipment({ transport_class: 'un3373', classification_basis: 'exempt_inactivated', coolant: 'dry_ice' }))).toEqual([
      'classification_basis: Choose the basis of the classification',
      'packing_instruction: UN 3373 is packed to P650',
      'coolant_kg: Give the quantity of dry ice: it is marked on the package',
    ])
  })
})
