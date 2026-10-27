import type { QueryClient } from '@tanstack/react-query'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent, { type UserEvent } from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { allowConsole } from '@/test/console'
import {
  makeBatch,
  makeBoxGrid,
  makeCheck,
  makeDeposit,
  makeDepositor,
  makeDepositRow,
  makeLab,
  makeLocationGrant,
  makeMe,
  makeMember,
  makeMedium,
  makeMtaTemplate,
  makePassage,
  makeStrain,
  makeStrainRow,
  makeTaxon,
  makeUnit,
  makeUnitRow,
  makeVial,
  makeRequest,
  makeRequester,
  makeRequestRow,
  makeActivityLine,
  makeHistoryLine,
  makeTerms,
  makeMyLab,
  makeOverview,
  makeLabPermit,
  makeReveal,
  makeWaitingGroup,
  makeWaitingItem,
  page,
} from '@/test/factories'
import { holdApi, mockApi, mockApiError, type PathFor } from '@/test/mockApi'
import { vialAction } from '@/test/actions'
import { renderApp } from '@/test/render'

// A failed background refetch keeps the data on screen (#63): the screen, its open dialog and
// what was typed in it stay, and a stale notice offers a retry. The full error shows only while
// a screen has no data (each screen's own tests cover that first load).

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const STRAIN_ID = '00000000-0000-4000-8000-0000000000d1'
const DEPOSIT_ID = '00000000-0000-4000-8000-0000000000d2'
const LAB = '/api/v1/labs/{public_id}/'
const STRAIN = '/api/v1/labs/{lab_public_id}/strains/{public_id}/'
const VIALS = '/api/v1/labs/{lab_public_id}/vials/'
const UNITS = '/api/v1/labs/{lab_public_id}/storage-units/'
const UNIT = '/api/v1/labs/{lab_public_id}/storage-units/{public_id}/'
const BOX = '/api/v1/labs/{lab_public_id}/boxes/{public_id}/'
const DEPOSIT = '/api/v1/labs/{lab_public_id}/deposits/{public_id}/'
const MEMBERS = '/api/v1/labs/{lab_public_id}/members/'
const DEPOSITORS = '/api/v1/labs/{lab_public_id}/depositors/'
const DEPOSITS = '/api/v1/labs/{lab_public_id}/deposits/'
const STRAINS = '/api/v1/labs/{lab_public_id}/strains/'
const MTAS = '/api/v1/labs/{lab_public_id}/mta-templates/'
const MTA = '/api/v1/labs/{lab_public_id}/mta-templates/{public_id}/'
const MEDIA = '/api/v1/labs/{lab_public_id}/media/'
const PERMITS = '/api/v1/labs/{lab_public_id}/permits/'
const REVEALS = '/api/v1/labs/{public_id}/reveals/'
const TERMS = '/api/v1/labs/{lab_public_id}/strains/{public_id}/terms/'
const HISTORY = '/api/v1/labs/{lab_public_id}/strains/{public_id}/history/'
const MATERIAL = `/labs/${LAB_ID}/strains/${STRAIN_ID}/material`
const SHIPMENTS = '/api/v1/labs/{lab_public_id}/strains/{public_id}/shipments/'

type Role = 'technician' | 'curator' | 'manager'
type Get = PathFor<'get'>

const freezer = makeUnitRow({ public_id: '00000000-0000-4000-8000-0000000000f1', name: 'Freezer A' })
const box = makeUnitRow({ public_id: '00000000-0000-4000-8000-0000000000f3', kind: 'box', name: 'Box 1', parent: freezer.public_id, rows: 9, cols: 9, max_risk_group: null })
const strain = makeStrain({ public_id: STRAIN_ID, accession_number: 'MYC 42', taxon: makeTaxon({ name: 'Testella exempli' }) })
const depositor = makeDepositor({ name: 'Jan Novák' })
const template = makeMtaTemplate({ code: 'MTA-A', version: 1, text: 'The recipient keeps the material in the lab.' })
const alice = makeMember({ username: 'alice', role: 'manager' })

function strainPage() {
  mockApi('get', STRAIN, strain)
  mockApi('get', '/api/v1/labs/{lab_public_id}/passages/', page([makePassage({ number: 0 })]))
  mockApi('get', '/api/v1/labs/{lab_public_id}/batches/', page([makeBatch()]))
  mockApi('get', VIALS, page([makeVial({ label: 'MYC 42 / 1 / 1' })]))
  mockApi('get', UNITS, [freezer, box])
  mockApi('get', TERMS, { deposit: null, versions: [makeTerms()] })
  mockApi('get', HISTORY, page([makeHistoryLine({ summary: 'accessioned MYC 42' })]))
}

/** A strain that left the collection (#20), still with an active restriction of an invented taxon. */
function leftPage() {
  const gmo = { public_id: '00000000-0000-4000-8000-0000000000e1', kind: 'gmo' as const, reference: 'MŽP 2026/12', act: '', gmo_category: 2, created_at: '2026-02-01T10:00:00Z', ended_at: null, end_reason: '', end_proposal: null }
  mockApi('get', STRAIN, {
    ...strain,
    status: 'deaccessioned',
    restriction_history: [gmo],
    regulated: true,
    deaccession: { deaccessioned_at: '2026-10-21T10:00:00Z', cause: 'contaminated', reason: 'Mixed culture.', final_use: '' },
  })
  mockApi('get', TERMS, { deposit: null, versions: [makeTerms()] })
  mockApi('get', SHIPMENTS, page([{ request: '00000000-0000-4000-8000-0000000000a1', number: '2026/3', institution: 'Example Institute', country: 'DE', shipped_at: '2026-06-01T10:00:00Z', vials: 2 }]))
}

type Screen = {
  /** The screen, the query whose refresh fails, the notice's words for it. */
  name: string
  role: Role
  path: string
  fails: Get
  what: string
  data: () => void
  /** Opens the dialog or form and returns the field it typed into. */
  type: (user: UserEvent) => Promise<HTMLElement>
}

const TYPED = 'typed before the refresh'

async function dialogField(user: UserEvent, trigger: string, field: string) {
  await user.click(await screen.findByRole('button', { name: trigger }, { timeout: 5000 }))
  const dialog = await screen.findByRole('dialog')
  const input = within(dialog).getByRole('textbox', { name: field })
  await user.clear(input)
  await user.type(input, TYPED)
  return input
}

/** The same through a menu button: the menu's item opens the dialog. */
async function menuField(user: UserEvent, menu: string, item: string, field: string) {
  await user.click(await screen.findByRole('button', { name: menu }, { timeout: 5000 }))
  await user.click(await screen.findByRole('menuitem', { name: item }))
  const dialog = await screen.findByRole('dialog')
  const input = within(dialog).getByRole('textbox', { name: field })
  await user.clear(input)
  await user.type(input, TYPED)
  return input
}

async function formField(user: UserEvent, field: string, role: 'textbox' | 'searchbox' = 'textbox') {
  const input = await screen.findByRole(role, { name: field }, { timeout: 5000 })
  await user.type(input, TYPED)
  return input
}

const SCREENS: Screen[] = [
  {
    name: 'LabGate, on the lab page with the add member form',
    role: 'manager',
    path: `/labs/${LAB_ID}`,
    fails: LAB,
    what: 'the lab',
    data: () => {
      mockApi('get', MEMBERS, page([alice]))
      mockApi('get', '/api/v1/labs/{lab_public_id}/location-grants/', [])
    },
    type: (user) => formField(user, 'Username'),
  },
  {
    name: 'LabGate, on the storage page with the add dialog',
    role: 'manager',
    path: `/labs/${LAB_ID}/storage`,
    fails: LAB,
    what: 'the lab',
    data: () => mockApi('get', UNITS, [freezer]),
    type: (user) => dialogField(user, 'Add a freezer or tank', 'Name'),
  },
  {
    name: 'UnitTree, with the add dialog',
    role: 'manager',
    path: `/labs/${LAB_ID}/storage`,
    fails: UNITS,
    what: 'the storage',
    data: () => mockApi('get', UNITS, [freezer]),
    type: (user) => dialogField(user, 'Add a freezer or tank', 'Name'),
  },
  {
    name: 'UnitDetail, with the change dialog',
    role: 'manager',
    path: `/labs/${LAB_ID}/storage/${freezer.public_id}`,
    fails: UNIT,
    what: 'the unit',
    data: () => mockApi('get', UNIT, makeUnit({ ...freezer })),
    type: (user) => dialogField(user, 'Change', 'Name'),
  },
  {
    name: 'BoxPositions, with a typed label',
    role: 'technician',
    path: `/labs/${LAB_ID}/storage/${box.public_id}`,
    fails: BOX,
    what: 'the positions',
    data: () => {
      mockApi('get', UNIT, makeUnit({ ...box }))
      mockApi('get', BOX, makeBoxGrid({ public_id: box.public_id }))
    },
    type: (user) => formField(user, 'Vial label or barcode'),
  },
  {
    name: 'StrainShell, with the add restriction dialog',
    role: 'manager',
    path: `/labs/${LAB_ID}/strains/${STRAIN_ID}`,
    fails: STRAIN,
    what: 'the strain',
    data: strainPage,
    type: (user) => menuField(user, 'Actions for MYC 42', 'Add a restriction', 'Reason'),
  },
  {
    name: 'ActiveTerms on the Overview tab, with the add restriction dialog',
    role: 'manager',
    path: `/labs/${LAB_ID}/strains/${STRAIN_ID}`,
    fails: TERMS,
    what: 'the terms',
    data: strainPage,
    type: (user) => menuField(user, 'Actions for MYC 42', 'Add a restriction', 'Reason'),
  },
  {
    name: 'StrainTerms, with the add restriction dialog',
    role: 'manager',
    path: `/labs/${LAB_ID}/strains/${STRAIN_ID}/terms`,
    fails: TERMS,
    what: 'the terms',
    data: strainPage,
    type: (user) => menuField(user, 'Actions for MYC 42', 'Add a restriction', 'Reason'),
  },
  {
    name: 'StrainShipments of a deaccessioned strain, with the propose end dialog',
    role: 'manager',
    path: `/labs/${LAB_ID}/strains/${STRAIN_ID}`,
    fails: SHIPMENTS,
    what: 'the shipments',
    data: leftPage,
    type: (user) => dialogField(user, 'Propose to end restriction MŽP 2026/12', 'Reason'),
  },
  {
    name: 'StrainHistory, with the reclassify dialog',
    role: 'manager',
    path: `/labs/${LAB_ID}/strains/${STRAIN_ID}/history`,
    fails: HISTORY,
    what: 'the history',
    data: strainPage,
    type: (user) => menuField(user, 'Actions for MYC 42', 'Reclassify', 'Reason'),
  },
  {
    name: 'StrainMaterial, with the preserve dialog',
    role: 'technician',
    path: MATERIAL,
    fails: VIALS,
    what: 'the vials',
    data: strainPage,
    type: (user) => dialogField(user, 'Preserve a batch', 'Protectant'),
  },
  {
    name: 'StrainMaterial passages, with the preserve dialog',
    role: 'technician',
    path: MATERIAL,
    fails: '/api/v1/labs/{lab_public_id}/passages/',
    what: 'the passages',
    data: strainPage,
    type: (user) => dialogField(user, 'Preserve a batch', 'Protectant'),
  },
  {
    name: 'StrainMaterial batches, with the preserve dialog',
    role: 'technician',
    path: MATERIAL,
    fails: '/api/v1/labs/{lab_public_id}/batches/',
    what: 'the batches',
    data: strainPage,
    type: (user) => dialogField(user, 'Preserve a batch', 'Protectant'),
  },
  {
    name: 'BatchChecks, with the record check dialog',
    role: 'technician',
    path: MATERIAL,
    fails: '/api/v1/labs/{lab_public_id}/batch-checks/',
    what: 'the checks',
    data: () => {
      strainPage()
      mockApi('get', '/api/v1/labs/{lab_public_id}/batch-checks/', page([makeCheck()]))
    },
    type: async (user) => {
      await user.click(await screen.findByRole('button', { name: 'Checks of batch 1' }, { timeout: 5000 }))
      await screen.findByRole('list', { name: 'Checks of batch 1' })
      return dialogField(user, 'Record a check', 'Note')
    },
  },
  {
    name: 'StrainList, with a typed search',
    role: 'manager',
    path: `/labs/${LAB_ID}/strains`,
    fails: STRAINS,
    what: 'the strains',
    data: () => mockApi('get', STRAINS, page([makeStrainRow({ accession_number: 'MYC 42' })])),
    type: (user) => formField(user, 'Number or name', 'searchbox'),
  },
  {
    name: 'DepositDetail, with the acceptance form',
    role: 'curator',
    path: `/labs/${LAB_ID}/deposits/${DEPOSIT_ID}`,
    fails: DEPOSIT,
    what: 'the deposit',
    data: () => mockApi('get', DEPOSIT, makeDeposit({ public_id: DEPOSIT_ID, status: 'checking' })),
    type: (user) => formField(user, 'Identification method'),
  },
  {
    name: 'DepositList, with a typed search',
    role: 'curator',
    path: `/labs/${LAB_ID}/deposits`,
    fails: DEPOSITS,
    what: 'the deposits',
    data: () => mockApi('get', DEPOSITS, page([makeDepositRow()])),
    type: (user) => formField(user, 'Name, depositor or number', 'searchbox'),
  },
  {
    name: 'DepositorList, with the change dialog',
    role: 'curator',
    path: `/labs/${LAB_ID}/depositors`,
    fails: DEPOSITORS,
    what: 'the depositors',
    data: () => mockApi('get', DEPOSITORS, page([depositor])),
    type: (user) => dialogField(user, 'Change Jan Novák', 'Postal address'),
  },
  {
    name: 'MemberTable, with the location grant dialog',
    role: 'manager',
    path: `/labs/${LAB_ID}`,
    fails: MEMBERS,
    what: 'the members',
    data: () => {
      mockApi('get', MEMBERS, page([alice]))
      mockApi('get', '/api/v1/labs/{lab_public_id}/location-grants/', [makeLocationGrant({ member: alice.public_id, username: 'alice' })])
    },
    type: (user) => dialogField(user, 'Revoke regulated locations for alice', 'Reason'),
  },
  {
    name: 'RequestList, with a typed search',
    role: 'curator',
    path: `/labs/${LAB_ID}/requests`,
    fails: '/api/v1/labs/{lab_public_id}/requests/',
    what: 'the requests',
    data: () => mockApi('get', '/api/v1/labs/{lab_public_id}/requests/', page([makeRequestRow()])),
    type: (user) => formField(user, 'Number, requester or strain', 'searchbox'),
  },
  {
    name: 'RequestDetail, with the approve dialog',
    role: 'curator',
    path: `/labs/${LAB_ID}/requests/${DEPOSIT_ID}`,
    fails: '/api/v1/labs/{lab_public_id}/requests/{public_id}/',
    what: 'the request',
    data: () => mockApi('get', '/api/v1/labs/{lab_public_id}/requests/{public_id}/', makeRequest({ public_id: DEPOSIT_ID })),
    type: (user) => dialogField(user, 'Approve and reserve the vials', 'Reason (optional)'),
  },
  {
    name: 'RequesterList, with the change dialog',
    role: 'curator',
    path: `/labs/${LAB_ID}/requesters`,
    fails: '/api/v1/labs/{lab_public_id}/requesters/',
    what: 'the requesters',
    data: () => mockApi('get', '/api/v1/labs/{lab_public_id}/requesters/', page([makeRequester({ institution: 'Example Institute' })])),
    type: (user) => dialogField(user, 'Change Example Institute', 'Company number'),
  },
]

async function closeDialog(user: UserEvent) {
  const dialog = screen.queryByRole('dialog')
  if (!dialog) return
  await user.keyboard('{Escape}')
  await waitFor(() => expect(dialog).not.toBeInTheDocument())
}

function signedIn(role: Role) {
  mockApi('get', '/api/v1/auth/me/', makeMe())
  mockApi('get', LAB, makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: role }))
}

/** A background refresh of every query on screen, as a window focus after the stale time does it. */
const refreshAll = (client: QueryClient) => client.refetchQueries({ type: 'active' })

const notice = (what: string) => screen.findByText(new RegExp(`^Could not refresh ${what}\\. What you see may be out of date\\.`), {}, { timeout: 5000 })

describe('a failed background refresh keeps the screen (#63)', { timeout: 30_000 }, () => {
  it.each(SCREENS.map((s) => [s.name, s] as const))('%s: the typed input stays, a stale notice offers a retry', async (_, s) => {
    allowConsole(/API error 500/)
    signedIn(s.role)
    s.data()
    const { client } = renderApp({ path: s.path })
    const user = userEvent.setup()
    const input = await s.type(user)
    expect(input).toHaveFocus()
    const failed = mockApiError('get', s.fails, 500)
    await refreshAll(client)
    expect(failed.length).toBeGreaterThan(0)
    const line = await notice(s.what)
    // Kept: the field, what was typed, and the focus on it. The notice is a polite status.
    expect(input).toBeInTheDocument()
    expect(input).toHaveValue(TYPED)
    expect(input).toHaveFocus()
    expect(line.closest('output')).not.toBeNull()
    // The reason, mapped (never the server's words): a 5xx.
    expect(line).toHaveTextContent(/out of date\. The server failed\. Try again in a moment\.$/)
    expect(screen.queryByText(/Could not load/)).not.toBeInTheDocument()

    // Retry: the data loads again and the notice goes. Behind an open dialog the notice is
    // inert like the rest of the page, so the dialog closes first.
    await closeDialog(user)
    s.data()
    if (s.fails === LAB) signedIn(s.role)
    await user.click(within(line.closest('output') ?? document.body).getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(screen.queryByText(/Could not refresh/)).not.toBeInTheDocument())
  })

  it.each([
    ['MtaTemplateDetail', `/labs/${LAB_ID}/mta-templates/${template.public_id}`, MTA, 'the MTA', () => mockApi('get', MTA, template), () => screen.findByText(template.text)],
    ['MtaTemplateList', `/labs/${LAB_ID}/mta-templates`, MTAS, 'the MTA templates', () => mockApi('get', MTAS, page([template])), () => screen.findByRole('link', { name: 'MTA-A version 1' })],
    ['MediaList', `/labs/${LAB_ID}/media`, MEDIA, 'the media', () => mockApi('get', MEDIA, page([makeMedium({ name: 'LB' })])), () => screen.findByRole('cell', { name: 'LB' })],
    ['PermitList', `/labs/${LAB_ID}/permits`, PERMITS, 'the permits', () => mockApi('get', PERMITS, [makeLabPermit({ permit_reference: 'DEV/VRAT/1' })]), () => screen.findByText('SÚJB DEV/VRAT/1')],
    ['RevealLog', `/labs/${LAB_ID}/reveals`, REVEALS, 'the reveals', () => mockApi('get', REVEALS, page([makeReveal({ vial_label: 'MYC 42 / 1 / 1' })])), () => screen.findByRole('link', { name: 'MYC 42 / 1 / 1' })],
    ['LabList', '/labs', '/api/v1/labs/', 'your labs', () => mockApi('get', '/api/v1/labs/', page([makeLab({ public_id: LAB_ID, name: 'Mycology' })])), () => screen.findByRole('link', { name: 'Mycology' })],
  ] as const)('%s keeps its rows and says they may be out of date', async (_, path, fails, what, data, shown) => {
    allowConsole(/API error 500/)
    signedIn('manager')
    data()
    const { client } = renderApp({ path })
    const before = await shown()
    mockApiError('get', fails as Get, 500)
    await refreshAll(client)
    await notice(what)
    expect(before).toBeInTheDocument()
    expect(screen.queryByText(/Could not load/)).not.toBeInTheDocument()
  })

  // A 404 on a refresh: the row is gone or no longer this user's. The screen stays, and the
  // notice says so in its own words.
  it.each([
    ['StrainShell', `/labs/${LAB_ID}/strains/${STRAIN_ID}`, STRAIN, 'the strain', strainPage, () => screen.findByRole('heading', { level: 1, name: 'MYC 42' })],
    ['StrainList', `/labs/${LAB_ID}/strains`, STRAINS, 'the strains', () => mockApi('get', STRAINS, page([makeStrainRow({ accession_number: 'MYC 42' })])), () => screen.findByRole('link', { name: 'MYC 42' })],
  ] as const)('%s says a 404 on a refresh means it no longer exists', async (_, path, fails, what, data, shown) => {
    signedIn('manager')
    data()
    const { client } = renderApp({ path })
    const before = await shown()
    mockApiError('get', fails as Get, 404)
    await refreshAll(client)
    const line = await notice(what)
    expect(line).toHaveTextContent(/out of date\. It no longer exists\. Reload the page\.$/)
    expect(before).toBeInTheDocument()
  })

  it('moves the focus to the heading when a retry from the notice works, never to the body', async () => {
    allowConsole(/API error 500/)
    signedIn('manager')
    mockApi('get', MTA, template)
    const { client } = renderApp({ path: `/labs/${LAB_ID}/mta-templates/${template.public_id}` })
    await screen.findByText(template.text, {}, { timeout: 5000 })
    mockApiError('get', MTA, 500)
    await refreshAll(client)
    const line = await notice('the MTA')
    const retry = within(line.closest('output') ?? document.body).getByRole('button', { name: 'Try again' })
    mockApi('get', MTA, template)
    await userEvent.setup().click(retry)
    await waitFor(() => expect(retry).not.toBeInTheDocument())
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('heading', { level: 1, name: 'MTA-A version 1' })))
  })

  it("moves the focus to the notice's section heading when a retry works", async () => {
    allowConsole(/API error 500/)
    signedIn('technician')
    strainPage()
    const { client } = renderApp({ path: MATERIAL })
    await screen.findByRole('table', { name: 'Vials' }, { timeout: 5000 })
    mockApiError('get', VIALS, 500)
    await refreshAll(client)
    const line = await notice('the vials')
    const retry = within(line.closest('output') ?? document.body).getByRole('button', { name: 'Try again' })
    strainPage()
    await userEvent.setup().click(retry)
    await waitFor(() => expect(retry).not.toBeInTheDocument())
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('heading', { level: 2, name: 'Vials' })))
  })

  it('keeps the retry focusable and sends one request while it runs', async () => {
    allowConsole(/API error 500/)
    signedIn('manager')
    mockApi('get', MTA, template)
    const { client } = renderApp({ path: `/labs/${LAB_ID}/mta-templates/${template.public_id}` })
    await screen.findByText(template.text, {}, { timeout: 5000 })
    mockApiError('get', MTA, 500)
    await refreshAll(client)
    const line = await notice('the MTA')
    const retry = within(line.closest('output') ?? document.body).getByRole('button', { name: 'Try again' })
    const held = holdApi('get', MTA)
    const user = userEvent.setup()
    await user.click(retry)
    await waitFor(() => expect(retry).toHaveAttribute('aria-disabled', 'true'))
    await user.click(retry)
    expect(retry).toHaveFocus()
    expect(held.calls).toHaveLength(1)
    held.release(500)
    await waitFor(() => expect(retry).toHaveAttribute('aria-disabled', 'false'))
    expect(held.calls).toHaveLength(1)
    expect(screen.getByText(template.text)).toBeInTheDocument()
  })

  // Data a dialog or a control reads besides the screen's own: a failed refresh keeps it too.
  it('keeps the box choices of an open place dialog', async () => {
    allowConsole(/API error 500/)
    signedIn('technician')
    strainPage()
    const { client } = renderApp({ path: MATERIAL })
    const user = userEvent.setup()
    await vialAction(user, 'MYC 42 / 1 / 1', 'Place')
    const dialog = await screen.findByRole('dialog')
    const choices = await within(dialog).findByRole('combobox', { name: 'Box' })
    await user.selectOptions(choices, box.public_id)
    mockApiError('get', UNITS, 500)
    await refreshAll(client)
    await waitFor(() => expect(client.getQueryState(['storage', LAB_ID, 'tree'])?.status).toBe('error'))
    expect(within(dialog).getByRole('combobox', { name: 'Box' })).toHaveValue(box.public_id)
    expect(within(within(dialog).getByRole('combobox', { name: 'Box' })).getAllByRole('option').map((o) => o.textContent)).toEqual(['Choose', 'Freezer A / Box 1'])
  })

  it('keeps the grant buttons of the members when the grants fail to refresh', async () => {
    allowConsole(/API error 500/)
    signedIn('manager')
    mockApi('get', MEMBERS, page([alice]))
    const GRANTS = '/api/v1/labs/{lab_public_id}/location-grants/'
    mockApi('get', GRANTS, [makeLocationGrant({ member: alice.public_id, username: 'alice' })])
    const { client } = renderApp({ path: `/labs/${LAB_ID}` })
    const revoke = await screen.findByRole('button', { name: 'Revoke regulated locations for alice' }, { timeout: 5000 })
    const failed = mockApiError('get', GRANTS, 500)
    await refreshAll(client)
    await waitFor(() => expect(failed.length).toBeGreaterThan(0))
    await waitFor(() => expect(client.isFetching()).toBe(0))
    expect(revoke).toBeInTheDocument()
    expect(screen.getByRole('row', { name: /alice/ })).toHaveTextContent('May see')
  })

  it('keeps the publish form and its text when the version it starts from fails to refresh', async () => {
    allowConsole(/API error 500/)
    signedIn('manager')
    mockApi('get', MTA, template)
    const { client } = renderApp({ path: `/labs/${LAB_ID}/mta-templates/new`, search: { from: template.public_id } })
    const user = userEvent.setup()
    const title = await screen.findByRole('textbox', { name: 'Title' }, { timeout: 5000 })
    await user.clear(title)
    await user.type(title, TYPED)
    const failed = mockApiError('get', MTA, 500)
    await refreshAll(client)
    await waitFor(() => expect(failed.length).toBeGreaterThan(0))
    await waitFor(() => expect(client.isFetching()).toBe(0))
    expect(title).toBeInTheDocument()
    expect(title).toHaveValue(TYPED)
    expect(screen.queryByText(/Could not load/)).not.toBeInTheDocument()
  })

  it('shows no error in an open move dialog when the storage fails to refresh', async () => {
    allowConsole(/API error 500/)
    signedIn('manager')
    const rack = makeUnitRow({ public_id: '00000000-0000-4000-8000-0000000000f2', kind: 'rack', name: 'Rack 1', parent: freezer.public_id })
    mockApi('get', UNIT, makeUnit({ ...rack }))
    mockApi('get', UNITS, [freezer, rack, makeUnitRow({ public_id: '00000000-0000-4000-8000-0000000000f4', name: 'Freezer B' })])
    const { client } = renderApp({ path: `/labs/${LAB_ID}/storage/${rack.public_id}` })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Move' }, { timeout: 5000 }))
    const dialog = await screen.findByRole('dialog', { name: 'Move Rack 1' })
    await within(dialog).findByRole('option', { name: 'Freezer B' })
    const failed = mockApiError('get', UNITS, 500)
    await refreshAll(client)
    await waitFor(() => expect(failed.length).toBeGreaterThan(0))
    await waitFor(() => expect(client.isFetching()).toBe(0))
    expect(within(dialog).queryByRole('alert')).not.toBeInTheDocument()
    expect(within(dialog).getByRole('option', { name: 'Freezer B' })).toBeInTheDocument()
  })

  it('shows the full error, and no notice, when the first load fails', async () => {
    allowConsole(/API error 500/)
    signedIn('manager')
    mockApiError('get', MTA, 500)
    renderApp({ path: `/labs/${LAB_ID}/mta-templates/${template.public_id}` })
    expect(await screen.findByText(/Could not load the MTA/, {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByText(/Could not refresh/)).not.toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})

// Home (#69) has no form: what stays is what was read, with a notice for each failed read.
function homeData() {
  mockApi('get', '/api/v1/me/overview/', makeOverview({ labs: [makeMyLab({ public_id: LAB_ID, name: 'Mycology', code: 'MYC' })], waiting: [makeWaitingGroup({ items: [makeWaitingItem({ lab: LAB_ID, subject: 'Testella exempli W1' })] })] }))
  mockApi('get', '/api/v1/me/activity/', { results: [makeActivityLine({ lab: LAB_ID, summary: 'accessioned MYC 42' })] })
}

describe('a failed background refresh keeps Home (#63, #69)', { timeout: 30_000 }, () => {
  it.each([
    ['the overview', '/api/v1/me/overview/', 'what waits for you'],
    ['the activity', '/api/v1/me/activity/', 'the activity'],
  ] as const)('%s: the lines stay, a stale notice offers a retry', async (_, fails, what) => {
    allowConsole(/API error 500/)
    mockApi('get', '/api/v1/auth/me/', makeMe())
    homeData()
    const { client } = renderApp({ path: '/' })
    expect(await screen.findByRole('link', { name: 'Testella exempli W1' }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'accessioned MYC 42' })).toBeInTheDocument()
    const failed = mockApiError('get', fails, 500)
    await refreshAll(client)
    expect(failed.length).toBeGreaterThan(0)
    const line = await notice(what)
    expect(line.closest('output')).not.toBeNull()
    expect(screen.getByRole('link', { name: 'Testella exempli W1' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'accessioned MYC 42' })).toBeInTheDocument()
    expect(screen.queryByText(/Could not load/)).not.toBeInTheDocument()
    homeData()
    const output = line.closest('output')
    expect(output).not.toBeNull()
    if (!output) return
    await userEvent.setup().click(within(output).getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(screen.queryByText(/Could not refresh/)).not.toBeInTheDocument())
  })
})
