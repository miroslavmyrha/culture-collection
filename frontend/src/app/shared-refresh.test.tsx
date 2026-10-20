import { screen, waitFor, within } from '@testing-library/react'
import userEvent, { type UserEvent } from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { vialKeys } from '@/features/vials/api/keys'
import {
  makeBatch,
  makeBoxGrid,
  makeDeposit,
  makeLab,
  makeLocationGrant,
  makeMe,
  makeMember,
  makePassage,
  makeStrain,
  makeStrainRow,
  makeTaxon,
  makeUnit,
  makeUnitRow,
  makeVial,
  page,
} from '@/test/factories'
import { mockApi } from '@/test/mockApi'
import { renderApp } from '@/test/render'

// Writes in one feature that change what another shows (lib/shared-keys.ts). Each case loads the
// other feature's data first, then writes, and counts the requests for that data after the write.

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const STRAIN_ID = '00000000-0000-4000-8000-0000000000d1'
const DEPOSIT_ID = '00000000-0000-4000-8000-0000000000d2'
const PASSAGES = '/api/v1/labs/{lab_public_id}/passages/'
const BATCHES = '/api/v1/labs/{lab_public_id}/batches/'
const VIALS = '/api/v1/labs/{lab_public_id}/vials/'
const UNITS = '/api/v1/labs/{lab_public_id}/storage-units/'
const UNIT = '/api/v1/labs/{lab_public_id}/storage-units/{public_id}/'
const STRAIN = '/api/v1/labs/{lab_public_id}/strains/{public_id}/'
const STRAINS = '/api/v1/labs/{lab_public_id}/strains/'
const BOX = '/api/v1/labs/{lab_public_id}/boxes/{public_id}/'
const GRANTS = '/api/v1/labs/{lab_public_id}/location-grants/'

// Invented taxa: the tests pair them with restrictions and risk groups.
const exempli = makeTaxon({ public_id: '00000000-0000-4000-8000-0000000000c1', name: 'Testella exempli' })
const mockia = makeTaxon({ public_id: '00000000-0000-4000-8000-0000000000c3', name: 'Mockia vulgaris' })
const GMO = {
  public_id: '00000000-0000-4000-8000-0000000000e1',
  kind: 'gmo' as const,
  reference: 'MŽP 2026/12',
  act: '',
  gmo_category: 2,
  created_at: '2026-02-01T10:00:00Z',
  ended_at: null,
  end_reason: '',
}
const regulated = makeStrain({ public_id: STRAIN_ID, accession_number: 'MYC 42', taxon: exempli, restriction_history: [GMO] })
const free = { ...regulated, restriction_history: [{ ...GMO, ended_at: '2026-10-20T10:00:00Z', end_reason: 'destroyed' }] }

const freezer = makeUnitRow({ public_id: '00000000-0000-4000-8000-0000000000f1', name: 'Freezer A' })
const box = makeUnitRow({ public_id: '00000000-0000-4000-8000-0000000000f3', kind: 'box', name: 'Box 1', parent: freezer.public_id, rows: 9, cols: 9, max_risk_group: null })
const where = (freezerName: string) => ({ box: box.public_id, box_name: 'Box 1', path: [freezerName, 'Box 1'], row: 1, col: 1, label: 'A1' })
const VIAL_ID = '00000000-0000-4000-8000-0000000000b1'
const masked = makeVial({ public_id: VIAL_ID, label: 'MYC 42 / 1 / 1', placed: true, location_masked: true })
const located = (freezerName = 'Freezer A') => ({ ...masked, location_masked: false, location: where(freezerName) })

type Role = 'technician' | 'curator' | 'manager'

function signedIn(role: Role) {
  mockApi('get', '/api/v1/auth/me/', makeMe())
  mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: role }))
}

/** The strain page's data. Returns the vial requests answered so far. */
function strainPage(strain = regulated, vial: ReturnType<typeof makeVial> = masked) {
  mockApi('get', STRAIN, strain)
  mockApi('get', PASSAGES, page([makePassage({ number: 0 })]))
  mockApi('get', BATCHES, page([makeBatch()]))
  return mockApi('get', VIALS, page([vial]))
}

const strainPath = `/labs/${LAB_ID}/strains/${STRAIN_ID}`
const vialRow = () => within(screen.getByRole('table', { name: 'Vials' })).getAllByRole('row')[1]

async function openStrainPage(role: Role, strain = regulated, vial: ReturnType<typeof makeVial> = masked) {
  signedIn(role)
  const first = strainPage(strain, vial)
  mockApi('get', UNITS, [freezer, box])
  const view = renderApp({ path: strainPath })
  await screen.findByRole('table', { name: 'Vials' }, { timeout: 5000 })
  expect(first).toHaveLength(1)
  return { ...view, user: userEvent.setup() }
}

async function inDialog(user: UserEvent, trigger: string, title: string, fill: (dialog: HTMLElement) => Promise<void>, confirm: string) {
  await user.click(await screen.findByRole('button', { name: trigger }))
  const dialog = await screen.findByRole('dialog', { name: title })
  await fill(dialog)
  await user.click(within(dialog).getByRole('button', { name: confirm }))
  await waitFor(() => expect(dialog).not.toBeInTheDocument(), { timeout: 5000 })
}

const STRAIN_WRITES: [string, (user: UserEvent) => Promise<void>][] = [
  [
    'adding a restriction',
    async (user) => {
      mockApi('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/restrictions/', { ...regulated, restriction_history: [GMO, { ...GMO, public_id: '00000000-0000-4000-8000-0000000000e2', reference: 'MŽP 2026/13' }] })
      await inDialog(
        user,
        'Add a restriction',
        'Add a restriction to MYC 42',
        async (dialog) => {
          await user.type(within(dialog).getByRole('textbox', { name: 'List entry' }), 'MŽP 2026/13')
          await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'listed')
        },
        'Add restriction',
      )
    },
  ],
  [
    'ending a restriction',
    async (user) => {
      mockApi('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/restrictions/{restriction_id}/end/', free)
      await inDialog(user, 'End restriction MŽP 2026/12', 'End the restriction MŽP 2026/12', (dialog) => user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'destroyed'), 'End restriction')
    },
  ],
  [
    'changing the risk group',
    async (user) => {
      mockApi('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/risk-group/', { ...regulated, risk_group: 1 })
      await inDialog(
        user,
        'Change risk group',
        'Change the risk group of MYC 42',
        async (dialog) => {
          await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Risk group' }), '1')
          await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'reassessed')
        },
        'Save risk group',
      )
    },
  ],
  [
    'reclassifying',
    async (user) => {
      mockApi('get', '/api/v1/taxa/', page([mockia]))
      mockApi('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/reclassify/', { ...regulated, taxon: { ...mockia } })
      await inDialog(
        user,
        'Reclassify',
        'Reclassify MYC 42',
        async (dialog) => {
          await user.click(within(dialog).getByRole('combobox', { name: 'Taxon' }))
          await user.keyboard('vulg')
          await screen.findByRole('option', { name: /Mockia vulgaris/ }, { timeout: 10_000 })
          await user.keyboard('{ArrowDown}{Enter}')
          await user.type(within(dialog).getByRole('textbox', { name: 'Method' }), 'MALDI-TOF MS')
          await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'the sequence differs')
        },
        'Save identification',
      )
    },
  ],
]

describe('a write refreshes the data other features show', { timeout: 30_000 }, () => {
  it.each(STRAIN_WRITES)("%s on the strain page refetches the strain's material and marks the lab's box grids stale", async (_, write) => {
    const { client, user } = await openStrainPage('manager')
    const grid = vialKeys.box(LAB_ID, box.public_id)
    client.setQueryData(grid, makeBoxGrid({ public_id: box.public_id }))
    const vials = mockApi('get', VIALS, page([masked]))
    const passages = mockApi('get', PASSAGES, page([makePassage({ number: 0 })]))
    await write(user)
    // The dialog closes only once the material is fresh: the requests are already made.
    expect(vials).toHaveLength(1)
    expect(passages).toHaveLength(1)
    expect(client.getQueryState(grid)?.isInvalidated).toBe(true)
  })

  it("ending a restriction shows the vial's location and the box grid's vial without a reload", async () => {
    const { router, user } = await openStrainPage('manager')
    expect(vialRow()).toHaveTextContent('Hidden: regulated strain')
    // The box grid as a reader saw it a moment ago: masked, and still fresh in the cache.
    signedIn('manager')
    mockApi('get', UNIT, makeUnit({ ...box }))
    mockApi('get', BOX, makeBoxGrid({ public_id: box.public_id, positions: [{ row: 1, col: 1, label: 'A1', masked: true, vial: null }] }))
    await router.navigate({ to: '/labs/$labId/storage/$unitId', params: { labId: LAB_ID, unitId: box.public_id } })
    expect(await screen.findByText('Position A1: a vial of a regulated strain. Which one is hidden.', {}, { timeout: 5000 })).toBeInTheDocument()
    await router.navigate({ to: '/labs/$labId/strains/$strainId', params: { labId: LAB_ID, strainId: STRAIN_ID } })
    await screen.findByRole('table', { name: 'Vials' })

    const vials = mockApi('get', VIALS, page([located()]))
    mockApi('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/restrictions/{restriction_id}/end/', free)
    await inDialog(user, 'End restriction MŽP 2026/12', 'End the restriction MŽP 2026/12', (dialog) => user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'destroyed'), 'End restriction')
    expect(vials).toHaveLength(1)
    expect(vialRow()).toHaveTextContent('Freezer A / Box 1, A1')

    const grids = mockApi('get', BOX, makeBoxGrid({ public_id: box.public_id, positions: [{ row: 1, col: 1, label: 'A1', masked: false, vial: { public_id: VIAL_ID, label: 'MYC 42 / 1 / 1', status: 'available', barcode: null, strain: STRAIN_ID, accession_number: 'MYC 42' } }] }))
    await router.navigate({ to: '/labs/$labId/storage/$unitId', params: { labId: LAB_ID, unitId: box.public_id } })
    await waitFor(() => expect(grids).toHaveLength(1), { timeout: 5000 })
    expect(await screen.findByText(/Position A1: MYC 42 \/ 1 \/ 1, available\./)).toBeInTheDocument()
  })

  it("adding a restriction hides a vial's location without a reload", async () => {
    const { user } = await openStrainPage('manager', free, located())
    expect(vialRow()).toHaveTextContent('Freezer A / Box 1, A1')
    const vials = mockApi('get', VIALS, page([masked]))
    mockApi('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/restrictions/', regulated)
    await inDialog(
      user,
      'Add a restriction',
      'Add a restriction to MYC 42',
      async (dialog) => {
        await user.type(within(dialog).getByRole('textbox', { name: 'List entry' }), 'MŽP 2026/12')
        await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'listed')
      },
      'Add restriction',
    )
    expect(vials).toHaveLength(1)
    expect(vialRow()).toHaveTextContent('Hidden: regulated strain')
    expect(vialRow()).not.toHaveTextContent('Box 1')
  })

  it("reads the storage tree and the vials' box choices from one entry", async () => {
    signedIn('technician')
    const units = mockApi('get', UNITS, [freezer, box])
    const { router } = renderApp({ path: `/labs/${LAB_ID}/storage` })
    await screen.findByRole('tree', { name: 'Storage of Mycology' }, { timeout: 5000 })
    strainPage(free, makeVial({ label: 'MYC 42 / 1 / 2' }))
    await router.navigate({ to: '/labs/$labId/strains/$strainId', params: { labId: LAB_ID, strainId: STRAIN_ID } })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Place vial MYC 42 / 1 / 2' }, { timeout: 5000 }))
    const dialog = await screen.findByRole('dialog')
    const choices = await within(dialog).findByRole('combobox', { name: 'Box' })
    expect(within(choices).getAllByRole('option').map((o) => o.textContent)).toEqual(['Choose', 'Freezer A / Box 1'])
    expect(units).toHaveLength(1)
  })

  it("a storage write refreshes the vials' box choices and their locations", async () => {
    const { router, user } = await openStrainPage('manager', free, located())
    expect(vialRow()).toHaveTextContent('Freezer A / Box 1, A1')
    mockApi('get', UNIT, makeUnit({ ...freezer, children: [] }))
    await router.navigate({ to: '/labs/$labId/storage/$unitId', params: { labId: LAB_ID, unitId: freezer.public_id } })
    const renamed = { ...freezer, name: 'Freezer B' }
    mockApi('post', '/api/v1/labs/{lab_public_id}/storage-units/{public_id}/edit/', makeUnit({ ...renamed }))
    const units = mockApi('get', UNITS, [renamed, box])
    const vials = mockApi('get', VIALS, page([located('Freezer B')]))
    await inDialog(
      user,
      'Change',
      'Change Freezer A',
      async (dialog) => {
        const name = within(dialog).getByRole('textbox', { name: 'Name' })
        await user.clear(name)
        await user.type(name, 'Freezer B')
      },
      'Save',
    )
    await router.navigate({ to: '/labs/$labId/strains/$strainId', params: { labId: LAB_ID, strainId: STRAIN_ID } })
    await waitFor(() => expect(vialRow()).toHaveTextContent('Freezer B / Box 1, A1'), { timeout: 5000 })
    expect(vials).toHaveLength(1)
    await user.click(screen.getByRole('button', { name: 'Move vial MYC 42 / 1 / 1' }))
    const choices = await within(await screen.findByRole('dialog')).findByRole('combobox', { name: 'Box' })
    expect(within(choices).getAllByRole('option').map((o) => o.textContent)).toEqual(['Choose', 'Freezer B / Box 1'])
    expect(units).toHaveLength(1)
  })

  it.each([
    ['granting', false, true],
    ['revoking', true, false],
  ] as const)('%s my own location grant on the lab page changes whether my vials offer a reveal', async (action, before, after) => {
    const { router, user } = await openStrainPage('manager', regulated, { ...masked, can_reveal: before })
    expect(within(vialRow() ?? document.body).queryAllByRole('button', { name: /Reveal the location/ })).toHaveLength(before ? 1 : 0)
    const me = makeMember({ username: 'alice', role: 'manager' })
    mockApi('get', '/api/v1/labs/{lab_public_id}/members/', page([me]))
    const grant = makeLocationGrant({ member: me.public_id, username: 'alice' })
    mockApi('get', GRANTS, before ? [grant] : [])
    await router.navigate({ to: '/labs/$labId', params: { labId: LAB_ID } })
    await screen.findByRole('table', { name: 'Members' }, { timeout: 5000 })
    if (action === 'granting') mockApi('post', GRANTS, grant)
    else mockApi('post', '/api/v1/labs/{lab_public_id}/location-grants/{public_id}/revoke/', undefined)
    const verb = action === 'granting' ? 'Grant' : 'Revoke'
    await user.click(await screen.findByRole('button', { name: `${verb} regulated locations for alice` }, { timeout: 5000 }))
    const dialog = await screen.findByRole('dialog', {}, { timeout: 5000 })
    // The answers after the write, registered only now: the grants loaded above stay as they were.
    mockApi('get', GRANTS, after ? [grant] : [])
    const vials = mockApi('get', VIALS, page([{ ...masked, can_reveal: after }]))
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'keeps the register')
    await user.click(within(dialog).getByRole('button', { name: verb }))
    // Waits of 5 s: under the load of the whole suite this flow takes longer than the default.
    await waitFor(() => expect(dialog).not.toBeInTheDocument(), { timeout: 5000 })
    await router.navigate({ to: '/labs/$labId/strains/$strainId', params: { labId: LAB_ID, strainId: STRAIN_ID } })
    await waitFor(() => expect(vials).toHaveLength(1), { timeout: 5000 })
    await waitFor(() => expect(within(vialRow() ?? document.body).queryAllByRole('button', { name: /Reveal the location/ })).toHaveLength(after ? 1 : 0), { timeout: 5000 })
  })

  it('accepting a deposit refreshes the lab\'s strain lists', async () => {
    signedIn('curator')
    mockApi('get', STRAINS, page([]))
    const { router } = renderApp({ path: `/labs/${LAB_ID}/strains` })
    expect(await screen.findByText('The lab has no strains yet.', {}, { timeout: 5000 })).toBeInTheDocument()
    const deposit = makeDeposit({ public_id: DEPOSIT_ID, name_as_received: 'T. exempli T1', status: 'checking' })
    mockApi('get', '/api/v1/labs/{lab_public_id}/deposits/{public_id}/', deposit)
    mockApi('get', '/api/v1/taxa/', page([exempli]))
    await router.navigate({ to: '/labs/$labId/deposits/$depositId', params: { labId: LAB_ID, depositId: DEPOSIT_ID } })
    const form = await screen.findByRole('form', { name: 'Accept the deposit' }, { timeout: 5000 })
    const user = userEvent.setup()
    await user.click(within(form).getByRole('combobox', { name: 'Taxon' }))
    await user.keyboard('exem')
    await screen.findByRole('option', { name: /Testella exempli/ }, { timeout: 10_000 })
    await user.keyboard('{ArrowDown}{Enter}')
    await user.type(within(form).getByRole('textbox', { name: 'Identification method' }), '16S rRNA gene sequence')
    await user.selectOptions(within(form).getByRole('combobox', { name: 'Risk group' }), '1')
    const accepted = mockApi('post', '/api/v1/labs/{lab_public_id}/deposits/{public_id}/accept/', { ...deposit, status: 'accepted', strain: { public_id: STRAIN_ID, accession_number: 'MYC 42' } })
    const strains = mockApi('get', STRAINS, page([makeStrainRow({ public_id: STRAIN_ID, accession_number: 'MYC 42' })]))
    await user.click(within(form).getByRole('button', { name: 'Accept and add the strain' }))
    await waitFor(() => expect(accepted).toHaveLength(1))
    await router.navigate({ to: '/labs/$labId/strains', params: { labId: LAB_ID } })
    expect(await screen.findByRole('link', { name: 'MYC 42' }, { timeout: 5000 })).toBeInTheDocument()
    expect(strains).toHaveLength(1)
  })
})
