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
    mat_uses: [],
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
export type CheckRow = Schemas['BatchCheckOutput']
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
    parent: null,
    source_vial_label: null,
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
    status_reason: '',
    status_changed_at: null,
    latest_checks: { identity: null, purity: null, viability: null },
    vial_count_created: 3,
    vials_available: 3,
    vials_distributable: 0,
    created_at: new Date(Date.UTC(2026, 0, 1, 0, 0, n)).toISOString(),
    ...overrides,
  }
}

/** A passed viability check after preservation, valid, without a vial. */
export function makeCheck(overrides: Partial<CheckRow> = {}): CheckRow {
  const n = next()
  return {
    public_id: uuid(n),
    batch: uuid(9003),
    batch_number: 1,
    kind: 'viability',
    stage: 'after_preservation',
    checked_on: '2026-10-02',
    performed_by: 'technician',
    method: 'growth',
    method_detail: '',
    result: 'pass',
    value: null,
    unit: '',
    vial: null,
    vial_label: null,
    note: '',
    status: 'valid',
    supersedes: null,
    reason: '',
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

export type BoxGrid = Schemas['BoxGridOutput']
export type BoxPosition = Schemas['BoxPosition']
export type BoxVial = Schemas['BoxVial']

/** An available vial of MYC 42 in a box. */
export function makeBoxVial(overrides: Partial<BoxVial> = {}): BoxVial {
  const n = next()
  return {
    public_id: uuid(n),
    label: `MYC 42 / 1 / ${n}`,
    status: 'available',
    barcode: null,
    strain: uuid(9001),
    accession_number: 'MYC 42',
    ...overrides,
  }
}

/** A taken position by its label ("B3"). 'masked' is what the API sends for a regulated strain: no vial. */
export function makePosition(label: string, vial: BoxVial | 'masked'): BoxPosition {
  const row = (label.codePointAt(0) ?? 64) - 64
  const col = Number(label.slice(1))
  return vial === 'masked' ? { row, col, label, masked: true, vial: null } : { row, col, label, masked: false, vial }
}

export function makeBoxGrid(overrides: Partial<BoxGrid> = {}): BoxGrid {
  const n = next()
  return { public_id: uuid(n), name: 'Box 1', rows: 9, cols: 9, positions: [], ...overrides }
}

// Distribution (#18). Invented institutions and people at example.org.
type RequestRow = components['schemas']['RequestListOutput']
type RequestDetail = components['schemas']['RequestDetailOutput']
type RequestLine = components['schemas']['LineOutput']
type Requester = components['schemas']['RequesterOutput']
type Permit = components['schemas']['PermitOutput']
type Finding = components['schemas']['Finding']
type Acceptance = components['schemas']['AcceptanceOutput']
type Shipment = components['schemas']['ShipmentOutput']
type ShipmentDocument = components['schemas']['ShipmentDocument']
type Preparation = components['schemas']['PreparationOutput']

export function makeRequestRow(overrides: Partial<RequestRow> = {}): RequestRow {
  const n = next()
  const at = new Date(Date.UTC(2026, 0, 1, 0, 0, n)).toISOString()
  return {
    public_id: uuid(n),
    number: `2026/${n}`,
    requester: { public_id: uuid(n + 1000), institution: 'Example Institute of Microbiology', country: 'CZ' },
    destination_country: 'CZ',
    use: 'research_noncommercial',
    status: 'submitted',
    line_count: 1,
    vial_count: 2,
    regulated: false,
    created_at: at,
    decided_at: null,
    ...overrides,
  }
}

export function makeRequestLine(overrides: Partial<RequestLine> = {}): RequestLine {
  const n = next()
  return {
    public_id: uuid(n),
    strain: { public_id: uuid(n + 2000), accession_number: `MYC ${n}`, taxon: 'Testella exempli', risk_group: 1 },
    quantity: 2,
    terms_version: 1,
    mta: { public_id: uuid(n + 3000), code: 'STD', version: 1, title: 'Standard MTA' },
    reserved: [],
    shipped: [],
    permits: [],
    ...overrides,
  }
}

export function makeFinding(overrides: Partial<Finding> = {}): Finding {
  return { code: 'mta_not_accepted', severity: 'block', sentence: 'MYC 1: no acceptance of MTA STD version 1 is recorded.', line: null, ...overrides }
}

export function makeAcceptance(overrides: Partial<Acceptance> = {}): Acceptance {
  const n = next()
  return {
    public_id: uuid(n),
    mta: { public_id: uuid(n + 3000), code: 'STD', version: 1, title: 'Standard MTA' },
    signer_name: 'Karel Podpisový',
    signer_role: 'head_of_institution',
    authorised_signatory: true,
    accepted_on: '2026-10-02',
    document: null,
    created_at: new Date(Date.UTC(2026, 0, 1, 0, 0, n)).toISOString(),
    ...overrides,
  }
}

export function makeRequest(overrides: Partial<RequestDetail> = {}): RequestDetail {
  const row = makeRequestRow()
  return {
    ...row,
    end_use: 'Teaching of antibiotic testing.',
    containment_level: 2,
    submitted_by: 'curator',
    decided_by: null,
    decision_reason: '',
    cancelled_by: null,
    cancelled_at: null,
    cancel_reason: '',
    lines: [makeRequestLine()],
    acceptances: [],
    findings: [],
    shipment: null,
    preparations: [],
    ...overrides,
  }
}

export function makeShipment(overrides: Partial<Shipment> = {}): Shipment {
  const n = next()
  const at = new Date(Date.UTC(2026, 9, 22, 8, 0, n)).toISOString()
  return {
    public_id: uuid(n),
    transport_class: 'not_subject',
    classification_basis: 'exempt_non_pathogenic',
    basis_note: '',
    classified_by: 'curator',
    classified_at: at,
    packing_instruction: 'triple_packaging',
    coolant: '',
    coolant_kg: null,
    responsible_name: 'Jan Odpovědný',
    responsible_phone: '+420 555 000 111',
    carrier: 'Example Courier',
    tracking_number: 'EX123456789CZ',
    shipped_by: 'curator',
    shipped_at: at,
    preparation: null,
    documents: [],
    ...overrides,
  }
}

export function makeShipmentDocument(overrides: Partial<ShipmentDocument> = {}): ShipmentDocument {
  const n = next()
  return {
    public_id: uuid(n),
    kind: 'delivery_note',
    strain: null,
    text_sha256: '3f'.repeat(32),
    created_at: new Date(Date.UTC(2026, 9, 22, 8, 0, n)).toISOString(),
    request: uuid(n + 1000),
    request_number: '2026/7',
    shipment: uuid(n + 2000),
    text: 'DELIVERY NOTE\n',
    ...overrides,
  }
}

export function makePreparation(overrides: Partial<Preparation> = {}): Preparation {
  const n = next()
  return {
    public_id: uuid(n),
    transport_class: 'not_subject',
    classification_basis: 'exempt_non_pathogenic',
    basis_note: '',
    packing_instruction: 'triple_packaging',
    coolant: '',
    coolant_kg: null,
    responsible_name: 'Jan Odpovědný',
    responsible_phone: '+420 555 000 111',
    carrier: 'Example Courier',
    tracking_number: 'EX123456789CZ',
    prepared_by: 'curator',
    prepared_at: new Date(Date.UTC(2026, 9, 21, 8, 0, n)).toISOString(),
    withdrawn_by: null,
    withdrawn_at: null,
    withdraw_reason: '',
    confirm_refusal: null,
    ...overrides,
  }
}

export function makePermit(overrides: Partial<Permit> = {}): Permit {
  const n = next()
  const at = new Date(Date.UTC(2026, 0, 1, 0, 0, n)).toISOString()
  return {
    public_id: uuid(n),
    requester: uuid(n + 1000),
    kind: 'sujb_rat_notice',
    issuer: 'SÚJB',
    issuer_country: 'CZ',
    reference: `DEV/${n} (invented example)`,
    valid_from: '2026-01-01',
    expires_on: null,
    covers: '',
    quantity_allowed: null,
    sendings_allowed: null,
    endorsement_reference: '',
    endorsed_on: null,
    gmo_category: null,
    risk_group: null,
    document: { public_id: uuid(n + 4000), content_type: 'application/pdf', size_bytes: 40, sha256: '0'.repeat(64), created_at: at },
    ended_on: null,
    end_reason: '',
    valid_today: true,
    created_at: at,
    ...overrides,
  }
}

export function makeRequester(overrides: Partial<Requester> = {}): Requester {
  const n = next()
  return {
    public_id: uuid(n),
    institution: `Example Institute ${n}`,
    legal_form: 'legal_person',
    registration_number: '',
    seat: '',
    country: 'CZ',
    lab_evidence: 'The department page lists a microbiology laboratory.',
    lab_confirmed_on: '2026-10-01',
    name: 'Petra Ukázková',
    email: 'petra@example.org',
    postal_address: 'Testovací 5, Brno',
    erased: false,
    permits: [],
    created_at: new Date(Date.UTC(2026, 0, 1, 0, 0, n)).toISOString(),
    ...overrides,
  }
}

// Home (#69)
export type Overview = components['schemas']['Overview']
export type WaitingGroup = components['schemas']['WaitingGroup']
export type WaitingItem = components['schemas']['WaitingItem']
export type MyLab = components['schemas']['MyLab']
export type ActivityLine = components['schemas']['ActivityLine']

export function makeWaitingItem(overrides: Partial<WaitingItem> = {}): WaitingItem {
  const n = next()
  return {
    lab: uuid(1000 + n),
    subject: `Testella exempli W${n}`,
    reason: 'Received, not checked yet',
    since: '2026-10-05',
    due: null,
    target: 'deposit',
    target_id: uuid(n),
    needs_manager: false,
    ...overrides,
  }
}

export function makeWaitingGroup(overrides: Partial<WaitingGroup> = {}): WaitingGroup {
  const items = overrides.items ?? [makeWaitingItem()]
  return { kind: 'deposit_received', total: items.length, items, ...overrides }
}

export function makeMyLab(overrides: Partial<MyLab> = {}): MyLab {
  const n = next()
  return {
    public_id: uuid(n),
    name: `Lab ${n}`,
    code: `L${n}`,
    role: 'viewer',
    strains: 0,
    batches: { pending_check: 0, released: 0, on_hold: 0, exhausted: 0 },
    vials_available: 0,
    free_positions: 0,
    open_requests: 0,
    requests_to_decide: null,
    deposits_to_check: null,
    actions: [],
    ...overrides,
  }
}

export function makeOverview(overrides: Partial<Overview> = {}): Overview {
  return { waiting: [], labs: [], ...overrides }
}

export type HistoryLine = Schemas['HistoryLine']

/** A line of a strain's history (#19): a line of Home's activity without the lab. */
export function makeHistoryLine(overrides: Partial<HistoryLine> = {}): HistoryLine {
  const n = next()
  return {
    occurred_at: new Date(Date.UTC(2026, 9, 23, 8, 0, n)).toISOString(),
    actor: `user:${uuid(2000 + n)}`,
    summary: `preserved MYC 42 batch ${n}`,
    target: 'strain',
    target_id: uuid(n),
    ...overrides,
  }
}

export function makeActivityLine(overrides: Partial<ActivityLine> = {}): ActivityLine {
  const n = next()
  return {
    occurred_at: new Date(Date.UTC(2026, 9, 23, 8, 0, n)).toISOString(),
    lab: uuid(1000 + n),
    lab_code: 'MYC',
    actor: `user:${uuid(2000 + n)}`,
    summary: `accessioned MYC ${n}`,
    target: 'strain',
    target_id: uuid(n),
    ...overrides,
  }
}

// The top bar's search (#76)
export type SearchHit = Schemas['SearchHit']
export type SearchGroup = Schemas['SearchGroup']

export const SEARCH_LAB = '00000000-0000-4000-8000-0000000000ba'

/** A strain hit of the lab SEARCH_LAB (BAC); a vial adds its strain and place. */
export function makeSearchHit(overrides: Partial<SearchHit> = {}): SearchHit {
  const n = next()
  return {
    public_id: uuid(n),
    lab: SEARCH_LAB,
    lab_code: 'BAC',
    identifier: `BAC ${n}`,
    title: 'Bacillus subtilis',
    detail: '',
    status: 'active',
    exact: false,
    strain: null,
    location: null,
    location_masked: false,
    ...overrides,
  }
}

/** A group of hits; the total and the lab's total count them unless given. */
export function makeSearchGroup(overrides: Partial<SearchGroup> = {}): SearchGroup {
  const hits = overrides.hits ?? [makeSearchHit()]
  const total = overrides.total ?? hits.length
  return { kind: 'strain', total, labs: [{ lab: SEARCH_LAB, lab_code: 'BAC', total }], hits, ...overrides }
}

export type LabPermit = Schemas['LabPermitOutput']

/** A valid SÚJB permit of the lab with an invented reference, no expiry stated. */
export function makeLabPermit(overrides: Partial<LabPermit> = {}): LabPermit {
  const n = next()
  return {
    public_id: uuid(n),
    kind: 'cz_vrat',
    kind_label: 'Permit to handle highly risky agents (VRAT)',
    issuer: 'sujb',
    issuer_label: 'SÚJB',
    permit_reference: `DEV/VRAT/${n}`,
    valid_from: '2026-01-01',
    expires_on: null,
    ended_on: null,
    end_reason: '',
    standing: 'valid',
    last_valid_day: null,
    days_left: null,
    ...overrides,
  }
}
