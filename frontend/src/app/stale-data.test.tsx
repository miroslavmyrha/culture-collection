import type { QueryClient } from '@tanstack/react-query'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent, { type UserEvent } from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { allowConsole } from '@/test/console'
import {
  makeBatch,
  makeBoxGrid,
  makeDeposit,
  makeDepositor,
  makeDepositRow,
  makeLab,
  makeLocationGrant,
  makeMe,
  makeMember,
  makeMtaTemplate,
  makePassage,
  makeStrain,
  makeStrainRow,
  makeTaxon,
  makeUnit,
  makeUnitRow,
  makeVial,
  page,
} from '@/test/factories'
import { holdApi, mockApi, mockApiError, type PathFor } from '@/test/mockApi'
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
    name: 'StrainDetail, with the add restriction dialog',
    role: 'manager',
    path: `/labs/${LAB_ID}/strains/${STRAIN_ID}`,
    fails: STRAIN,
    what: 'the strain',
    data: strainPage,
    type: (user) => dialogField(user, 'Add a restriction', 'Reason'),
  },
  {
    name: 'StrainMaterial, with the preserve dialog',
    role: 'technician',
    path: `/labs/${LAB_ID}/strains/${STRAIN_ID}`,
    fails: VIALS,
    what: 'the vials',
    data: strainPage,
    type: (user) => dialogField(user, 'Preserve a batch', 'Protectant'),
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
