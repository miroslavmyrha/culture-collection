import type { components } from '@/api/schema'
import type { Problem, ProblemError } from '@/lib/api'

export type Me = components['schemas']['MeOutput']
export type Paginated<T> = { count: number; next: string | null; previous: string | null; results: T[] }

// A counter, not random values: unique and repeatable.
let seq = 0
const next = () => ++seq
export const resetFactories = () => {
  seq = 0
}
const uuid = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`

export function makeMe(overrides: Partial<Me> = {}): Me {
  const n = next()
  return { public_id: uuid(n), username: `user-${n}`, first_name: '', last_name: '', email: `user-${n}@example.org`, ...overrides }
}

export function page<T>(results: T[], overrides: Partial<Paginated<T>> = {}): Paginated<T> {
  return { count: results.length, next: null, previous: null, results, ...overrides }
}

/** A problem-details body as the backend sends it for 4xx. */
export function problem(status: number, overrides: Partial<Problem> = {}): Problem {
  return { type: 'about:blank', title: 'Error', status, detail: 'Request failed.', code: 'error', ...overrides }
}

export function validationProblem(errors: ProblemError[]): Problem {
  return problem(400, { title: 'Invalid input.', detail: 'Invalid input.', code: 'invalid', errors })
}

export type Lab = components['schemas']['LabOutput']
export type Member = components['schemas']['MemberOutput']

export function makeLab(overrides: Partial<Lab> = {}): Lab {
  const n = next()
  return { public_id: uuid(n), name: `Lab ${n}`, code: `L${n}`, my_role: 'viewer', ...overrides }
}

export function makeMember(overrides: Partial<Member> = {}): Member {
  const n = next()
  const at = new Date(Date.UTC(2026, 0, 1, 0, 0, n)).toISOString()
  return { public_id: uuid(n), username: `member-${n}`, first_name: '', last_name: '', role: 'viewer', created_at: at, ...overrides }
}

type Schemas = components['schemas']
export type Taxon = Schemas['TaxonOutput']
export type StrainRow = Schemas['StrainListOutput']
export type Strain = Schemas['StrainDetailOutput']

export function makeTaxon(overrides: Partial<Taxon> = {}): Taxon {
  const n = next()
  return { public_id: uuid(n), name: `Genus species${n}`, authority: '', rank: 'species', status: 'accepted', parent: null, accepted: null, identifiers: [], ...overrides }
}

const brief = ({ public_id, name, authority, rank, status }: Taxon) => ({ public_id, name, authority, rank, status })

export function makeStrainRow(overrides: Partial<StrainRow> = {}): StrainRow {
  const n = next()
  const at = new Date(Date.UTC(2026, 0, 1, 0, 0, n)).toISOString()
  return {
    public_id: uuid(n),
    accession_number: `MYC ${n}`,
    name_as_received: `strain ${n}`,
    taxon: brief(makeTaxon()),
    risk_group: 1,
    status: 'active',
    restrictions: [],
    created_at: at,
    ...overrides,
  }
}

export function makeStrain(overrides: Partial<Strain> = {}): Strain {
  const row = makeStrainRow()
  const n = next()
  return {
    ...row,
    animal_pathogenicity: 'unknown',
    plant_pathogenicity: 'unknown',
    isolation_source: '',
    country_of_origin: '',
    isolation_date: '',
    identifications: [
      {
        public_id: uuid(n),
        taxon: row.taxon,
        identified_on: '2026-01-10',
        method: '16S rRNA gene sequence',
        reason: 'Identification at accession',
        is_current: true,
        created_at: row.created_at,
      },
    ],
    restriction_history: [],
    ...overrides,
  }
}

export type Depositor = Schemas['DepositorOutput']
export type MtaTemplate = Schemas['MtaTemplateDetailOutput']
export type Terms = Schemas['TermsOutput']
export type DepositRow = Schemas['DepositListOutput']
export type Deposit = Schemas['DepositDetailOutput']

const USES = [
  'research_noncommercial',
  'research_commercial',
  'teaching',
  'diagnostics',
  'production',
  'reference_qc',
  'patent_deposit_related',
  'redistribution',
] as const

/** Invented people at example.org: a depositor is personal data. */
export function makeDepositor(overrides: Partial<Depositor> = {}): Depositor {
  const n = next()
  const at = new Date(Date.UTC(2026, 0, 1, 0, 0, n)).toISOString()
  return {
    public_id: uuid(n),
    name: `Depositor ${n}`,
    institution: 'Example University',
    erased: false,
    email: `depositor-${n}@example.org`,
    postal_address: '',
    created_at: at,
    ...overrides,
  }
}

export function makeMtaTemplate(overrides: Partial<MtaTemplate> = {}): MtaTemplate {
  const n = next()
  const at = new Date(Date.UTC(2026, 0, 1, 0, 0, n)).toISOString()
  return { public_id: uuid(n), code: 'STD', version: 1, title: 'Standard MTA', text_sha256: 'ab'.repeat(32), created_at: at, text: 'Terms.', ...overrides }
}

export function makeTerms(overrides: Partial<Terms> = {}): Terms {
  const n = next()
  const at = new Date(Date.UTC(2026, 0, 1, 0, 0, n)).toISOString()
  return {
    public_id: uuid(n),
    version: 1,
    is_active: true,
    mta: null,
    abs_scope: 'not_in_scope',
    country_of_origin: '',
    collection_date: '',
    pic_reference: '',
    mat_reference: '',
    ircc: '',
    permit_reference: '',
    reason: '',
    uses: USES.map((use) => ({ use, decision: 'permit' as const })),
    created_at: at,
    ...overrides,
  }
}

export function makeDepositRow(overrides: Partial<DepositRow> = {}): DepositRow {
  const n = next()
  const at = new Date(Date.UTC(2026, 0, 1, 0, 0, n)).toISOString()
  const { public_id, name, institution, erased } = makeDepositor()
  return {
    public_id: uuid(n),
    status: 'received',
    received_on: '2026-10-01',
    name_as_received: `Testella exempli D${n}`,
    depositor: { public_id, name, institution, erased },
    strain: null,
    created_at: at,
    ...overrides,
  }
}

export function makeDeposit(overrides: Partial<Deposit> = {}): Deposit {
  const terms = makeTerms()
  return {
    ...makeDepositRow(),
    condition: 'intact',
    condition_note: '',
    depositor_passages: null,
    decided_at: null,
    rejection_reason: '',
    terms,
    terms_history: [terms],
    ...overrides,
  }
}

export type UnitRow = Schemas['UnitOutput']
export type Unit = Schemas['UnitDetailOutput']
export type BoxType = Schemas['BoxTypeOutput']

export function makeBoxType(overrides: Partial<BoxType> = {}): BoxType {
  const n = next()
  return { public_id: uuid(n), name: `Cryobox ${n}`, rows: 9, cols: 9, ...overrides }
}

/** A freezer by default; a rack or box needs `parent`, a box also its size. */
export function makeUnitRow(overrides: Partial<UnitRow> = {}): UnitRow {
  const n = next()
  const at = new Date(Date.UTC(2026, 0, 1, 0, 0, n)).toISOString()
  return {
    public_id: uuid(n),
    kind: 'freezer',
    name: `Freezer ${n}`,
    parent: null,
    slot: null,
    barcode: null,
    status: 'active',
    box_type: null,
    rows: null,
    cols: null,
    temperature_c: null,
    max_risk_group: 2,
    effective_max_risk_group: 2,
    path_active: true,
    created_at: at,
    retired_at: null,
    ...overrides,
  }
}

export function makeUnit(overrides: Partial<Unit> = {}): Unit {
  return { ...makeUnitRow(), ancestors: [], children: [], ...overrides }
}

export type PassageRow = Schemas['PassageOutput']
export type BatchRow = Schemas['BatchOutput']
export type VialRow = Schemas['VialOutput']
export type LocationGrant = Schemas['LocationGrantOutput']

export function makePassage(overrides: Partial<PassageRow> = {}): PassageRow {
  const n = next()
  return {
    public_id: uuid(n),
    strain: uuid(9000),
    number: 0,
    source_kind: 'deposit',
    source_passage: null,
    source_vial: null,
    created_at: new Date(Date.UTC(2026, 0, 1, 0, 0, n)).toISOString(),
    ...overrides,
  }
}

export function makeBatch(overrides: Partial<BatchRow> = {}): BatchRow {
  const n = next()
  return {
    public_id: uuid(n),
    strain: uuid(9000),
    number: 1,
    passage: uuid(9001),
    passage_number: 0,
    method: 'cryo_minus80',
    cryoprotectant: '10 % glycerol',
    preserved_on: '2026-10-01',
    purpose: 'distribution',
    status: 'pending_check',
    vial_count_created: 3,
    vials_available: 3,
    created_at: new Date(Date.UTC(2026, 0, 1, 0, 0, n)).toISOString(),
    ...overrides,
  }
}

/** Available and not placed by default. */
export function makeVial(overrides: Partial<VialRow> = {}): VialRow {
  const n = next()
  return {
    public_id: uuid(n),
    label: `MYC 42 / 1 / ${n}`,
    batch: uuid(9002),
    batch_number: 1,
    seq: n,
    barcode: null,
    status: 'available',
    status_changed_at: null,
    placed: false,
    location: null,
    location_masked: false,
    can_reveal: false,
    ...overrides,
  }
}

export function makeLocationGrant(overrides: Partial<LocationGrant> = {}): LocationGrant {
  const n = next()
  return { public_id: uuid(n), member: uuid(9003), username: 'bob', reason: 'keeps the register', created_at: '2026-10-01T10:00:00Z', ...overrides }
}
