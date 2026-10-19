import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeBoxType, makeUnit, makeUnitRow, page, problem, type Unit, validationProblem } from '@/test/factories'
import { holdApi, mockApi, mockApiError } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { storageKeys } from '../api/keys'
import { UnitDetail } from './UnitDetail'
import { moveTargets } from './UnitDialogs'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const DETAIL = '/api/v1/labs/{lab_public_id}/storage-units/{public_id}/'
const TREE = '/api/v1/labs/{lab_public_id}/storage-units/'
const freezer = { public_id: '00000000-0000-4000-8000-0000000000f1', kind: 'freezer' as const, name: 'Freezer A' }
const cryobox = makeBoxType({ public_id: '00000000-0000-4000-8000-0000000000c9', name: '81-place cryobox (9 x 9)' })
const rack = makeUnit({
  public_id: '00000000-0000-4000-8000-0000000000a1',
  kind: 'rack',
  name: 'Rack 1',
  parent: freezer.public_id,
  slot: 1,
  max_risk_group: null,
  effective_max_risk_group: 2,
  ancestors: [freezer],
  children: [
    { public_id: '00000000-0000-4000-8000-0000000000b1', kind: 'box', name: 'Box 1', slot: 1, status: 'active', rows: 9, cols: 9 },
    { public_id: '00000000-0000-4000-8000-0000000000b2', kind: 'box', name: 'Box 2', slot: null, status: 'retired', rows: 10, cols: 10 },
  ],
})
const box = makeUnit({
  public_id: '00000000-0000-4000-8000-0000000000b1',
  kind: 'box',
  name: 'Box 1',
  parent: rack.public_id,
  slot: 1,
  box_type: cryobox,
  rows: 9,
  cols: 9,
  max_risk_group: 3,
  effective_max_risk_group: 2,
  ancestors: [freezer, { public_id: rack.public_id, kind: 'rack', name: 'Rack 1' }],
})

async function render(unit = rack, { canManage = true, onCreated = vi.fn<(created: Unit) => void>() } = {}) {
  const result = await renderWithProviders(<UnitDetail labId={LAB_ID} labName="Mycology" unitId={unit.public_id} canManage={canManage} onCreated={onCreated} />)
  return { ...result, onCreated }
}

const facts = () => Object.fromEntries([...document.querySelectorAll('dt')].map((dt) => [dt.textContent, dt.nextElementSibling?.textContent]))

describe('UnitDetail', { timeout: 20_000 }, () => {
  it('shows where the unit is, what it is and what it holds', async () => {
    mockApi('get', DETAIL, rack)
    await render()
    expect(screen.getByText('Loading the unit…')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { level: 1, name: 'Rack 1' })).toBeInTheDocument()
    expect(document.title).toBe('Rack 1 in Freezer A | Culture collection')
    const crumbs = within(screen.getByRole('navigation', { name: 'Breadcrumb' })).getAllByRole('listitem')
    expect(crumbs.map((li) => li.textContent)).toEqual(['Storage of Mycology/', 'Freezer A/', 'Rack 1'])
    expect(within(screen.getByRole('navigation', { name: 'Breadcrumb' })).getByRole('link', { name: 'Freezer A' })).toHaveAttribute('href', `/labs/${LAB_ID}/storage/${freezer.public_id}`)
    expect(crumbs[2]).toHaveAttribute('aria-current', 'page')
    expect(facts()).toEqual({ Kind: 'Rack', Status: 'Active', Slot: '1', 'Highest risk group': '2, set above it', Barcode: 'None' })
    const holds = screen.getByRole('table', { name: 'What Rack 1 holds' })
    expect(within(holds).getAllByRole('row').slice(1).map((row) => row.textContent)).toEqual(['1Box 1Box9 x 9Active', 'Box 2Box10 x 10Retired'])
    expect(screen.getByRole('region', { name: 'Holds table' })).toHaveAttribute('tabindex', '0')
  })

  it('shows a box with its size from A1 and a cap lowered above it', async () => {
    mockApi('get', DETAIL, box)
    await render(box)
    await screen.findByRole('heading', { level: 1, name: 'Box 1' })
    expect(facts()).toMatchObject({ Size: '9 x 9, A1 to I9', 'Box type': '81-place cryobox (9 x 9)', 'Highest risk group': '2, lower above it than its own 3' })
    expect(screen.queryByRole('heading', { name: 'Holds' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Add a/ })).not.toBeInTheDocument() // a box holds no unit
  })

  it('offers no changes to a role that may only read, nor on a retired unit', async () => {
    mockApi('get', DETAIL, rack)
    const { unmount } = await render(rack, { canManage: false })
    await screen.findByRole('heading', { level: 1, name: 'Rack 1' })
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    unmount()
    mockApi('get', DETAIL, { ...rack, status: 'retired', retired_at: '2026-05-01T10:00:00Z' })
    await render()
    await screen.findByRole('heading', { level: 1, name: 'Rack 1' })
    expect(facts().Status).toBe('Retired')
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('says a unit it cannot find is not found, with its title', async () => {
    mockApiError('get', DETAIL, 404, problem(404, { code: 'not_found' }))
    await render()
    expect(await screen.findByRole('heading', { level: 1, name: 'Unit not found' })).toBeInTheDocument()
    expect(document.title).toBe('Unit not found | Culture collection')
  })

  it('shows a failed load with a retry, titled', async () => {
    allowConsole(/API error 500/)
    mockApiError('get', DETAIL, 500)
    await render()
    expect(await screen.findByText(/Could not load the unit/)).toBeInTheDocument()
    expect(document.title).toBe('Could not load the unit | Culture collection')
    mockApi('get', DETAIL, rack)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Rack 1' })).toBeInTheDocument()
  })

  it('adds a box inside by keyboard with its type and slot, then shows it', async () => {
    mockApi('get', DETAIL, rack)
    mockApi('get', '/api/v1/box-types/', page([cryobox]))
    const calls = mockApi('post', TREE, box)
    const { onCreated } = await render()
    const user = userEvent.setup()
    const add = await screen.findByRole('button', { name: 'Add a box' })
    add.focus()
    await user.keyboard('{Enter}')
    const dialog = await screen.findByRole('dialog', { name: 'Add a box to Rack 1' })
    // A rack holds only boxes: no kind to choose, the name comes first.
    expect(within(dialog).queryByRole('combobox', { name: 'Kind' })).not.toBeInTheDocument()
    await waitFor(() => expect(within(dialog).getByRole('textbox', { name: 'Name' })).toHaveFocus())
    await user.keyboard('Box 1')
    const type = within(dialog).getByRole('combobox', { name: 'Box type' })
    await within(dialog).findByRole('option', { name: '81-place cryobox (9 x 9)' })
    await user.selectOptions(type, cryobox.public_id)
    await user.type(within(dialog).getByRole('textbox', { name: 'Slot' }), '1')
    expect(within(dialog).queryByRole('textbox', { name: 'Temperature (°C)' })).not.toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(box))
    expect(calls[0]?.headers.get('X-CSRFToken')).toBe('test-token')
    expect(calls[0]?.body).toEqual({ kind: 'box', parent: rack.public_id, slot: 1, name: 'Box 1', barcode: '', temperature_c: null, max_risk_group: null, box_type: cryobox.public_id })
  })

  it('checks the box type before any request, and puts a taken name on its field', async () => {
    mockApi('get', DETAIL, rack)
    mockApi('get', '/api/v1/box-types/', page([cryobox]))
    const calls = mockApiError('post', TREE, 400, validationProblem([{ attr: 'name', code: 'unique', detail: 'A unit here has this name already.' }]))
    await render()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Add a box' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByRole('textbox', { name: 'Name' }), 'Box 1')
    await user.click(within(dialog).getByRole('button', { name: 'Add' }))
    const type = within(dialog).getByRole('combobox', { name: 'Box type' })
    await waitFor(() => expect(type).toHaveAccessibleDescription("Its rows and columns become the box's size. Choose the box type"))
    expect(type).toHaveFocus()
    expect(calls).toHaveLength(0)
    await user.selectOptions(type, cryobox.public_id)
    await user.click(within(dialog).getByRole('button', { name: 'Add' }))
    const name = within(dialog).getByRole('textbox', { name: 'Name' })
    await waitFor(() => expect(name).toHaveAccessibleDescription('A unit here has this name already.'))
    expect(name).toHaveFocus()
  })

  it('shows a refused parent, which has no field here, as the dialog message', async () => {
    mockApi('get', DETAIL, rack)
    mockApi('get', '/api/v1/box-types/', page([cryobox]))
    mockApiError('post', TREE, 400, validationProblem([{ attr: 'parent', code: 'parent_not_active', detail: 'This unit is out of service or retired: nothing goes in.' }]))
    await render()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Add a box' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByRole('textbox', { name: 'Name' }), 'Box 9')
    await within(dialog).findByRole('option', { name: cryobox.name })
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Box type' }), cryobox.public_id)
    await user.click(within(dialog).getByRole('button', { name: 'Add' }))
    expect(await within(dialog).findByText('This unit is out of service or retired: nothing goes in.')).toBeInTheDocument()
  })

  it('changes the name, and the answer becomes the unit on screen', async () => {
    mockApi('get', DETAIL, rack)
    const renamed = { ...rack, name: 'Rack 1a' }
    const calls = mockApi('post', `${DETAIL}edit/` as '/api/v1/labs/{lab_public_id}/storage-units/{public_id}/edit/', renamed)
    const { client } = await render()
    const user = userEvent.setup()
    const trigger = await screen.findByRole('button', { name: 'Change' })
    await user.click(trigger)
    const dialog = await screen.findByRole('dialog', { name: 'Change Rack 1' })
    const name = within(dialog).getByRole('textbox', { name: 'Name' })
    await waitFor(() => expect(name).toHaveFocus())
    await user.clear(name)
    await user.keyboard('Rack 1a')
    await user.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ name: 'Rack 1a', barcode: '', temperature_c: null, max_risk_group: null, box_type: null })
    expect(client.getQueryData(storageKeys.detail(LAB_ID, rack.public_id))).toEqual(renamed)
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('moves the unit into a place that may take it, never into itself or below it', async () => {
    const tank = makeUnitRow({ public_id: '00000000-0000-4000-8000-0000000000f2', kind: 'ln2_tank', name: 'Tank B' })
    const tree = [
      makeUnitRow({ ...freezer }),
      makeUnitRow({ public_id: rack.public_id, kind: 'rack', name: 'Rack 1', parent: freezer.public_id, slot: 1 }),
      makeUnitRow({ public_id: box.public_id, kind: 'box', name: 'Box 1', parent: rack.public_id, rows: 9, cols: 9 }),
      tank,
    ]
    mockApi('get', DETAIL, rack)
    const treeCalls = mockApi('get', TREE, tree)
    const moved = { ...rack, parent: tank.public_id, ancestors: [{ public_id: tank.public_id, kind: 'ln2_tank' as const, name: 'Tank B' }] }
    const calls = mockApi('post', '/api/v1/labs/{lab_public_id}/storage-units/{public_id}/move/', moved)
    const { client } = await render()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Move' }))
    const dialog = await screen.findByRole('dialog', { name: 'Move Rack 1' })
    expect(dialog).toHaveAccessibleDescription('Everything in Rack 1 moves with it.')
    const into = within(dialog).getByRole('combobox', { name: 'Into' })
    await within(dialog).findByRole('option', { name: 'Tank B' })
    // Freezer A is where it is now; Rack 1 and Box 1 are itself and below it.
    expect(within(into).getAllByRole('option').map((o) => o.textContent)).toEqual(['Choose', 'Tank B'])
    await user.selectOptions(into, tank.public_id)
    await user.type(within(dialog).getByRole('textbox', { name: 'Slot' }), '3')
    await user.click(within(dialog).getByRole('button', { name: 'Move' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ parent: tank.public_id, slot: 3 })
    // The answer is the unit itself; the lab's tree is stale now, so it is read again.
    expect(client.getQueryData(storageKeys.detail(LAB_ID, rack.public_id))).toEqual(moved)
    expect(client.getQueryState(storageKeys.detail(LAB_ID, rack.public_id))?.isInvalidated).toBe(false)
    expect(treeCalls).toHaveLength(2)
  })

  it('puts the unit out of service with a reason, asked before any request', async () => {
    mockApi('get', DETAIL, rack)
    const held = holdApi('post', '/api/v1/labs/{lab_public_id}/storage-units/{public_id}/status/')
    await render()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Put out of service' }))
    const dialog = await screen.findByRole('dialog', { name: 'Put Rack 1 out of service' })
    await user.click(within(dialog).getByRole('button', { name: 'Out of service' }))
    expect(within(dialog).getByRole('textbox', { name: 'Reason' })).toHaveAccessibleDescription('Stored for good with the change. Name no person. Say why')
    expect(held.calls).toHaveLength(0)
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'alarm')
    await user.click(within(dialog).getByRole('button', { name: 'Out of service' }))
    await waitFor(() => expect(held.calls).toHaveLength(1))
    expect(held.calls[0]?.body).toEqual({ status: 'out_of_service', reason: 'alarm' })
    // Pending: Escape does not close it, the confirm button keeps its focus.
    await user.keyboard('{Escape}')
    expect(dialog).toBeInTheDocument()
    held.release(200, { ...rack, status: 'out_of_service' })
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
  })

  it('retires in an alertdialog that opens on Cancel, and shows why a unit that holds something stays', async () => {
    mockApi('get', DETAIL, rack)
    mockApiError('post', '/api/v1/labs/{lab_public_id}/storage-units/{public_id}/status/', 422, problem(422, { code: 'unit_not_empty' }))
    await render()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Retire' }))
    const dialog = await screen.findByRole('alertdialog', { name: 'Retire Rack 1?' })
    expect(dialog).toHaveAccessibleDescription(expect.stringContaining('This cannot be undone.'))
    await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus())
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'replaced')
    await user.click(within(dialog).getByRole('button', { name: 'Retire' }))
    expect(await within(dialog).findByText('The unit still holds units that are not retired. Move or retire them first.')).toBeInTheDocument()
  })

  it('says a unit retired meanwhile changes no more', async () => {
    mockApi('get', DETAIL, rack)
    mockApiError('post', '/api/v1/labs/{lab_public_id}/storage-units/{public_id}/edit/', 409, problem(409, { code: 'unit_retired' }))
    await render()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Change' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(await within(dialog).findByText('This unit is retired and changes no more. Reload to see it.')).toBeInTheDocument()
  })
})

describe('moveTargets', () => {
  it('offers active units of a kind that may hold it, so never the unit or anything below it', () => {
    const f = makeUnitRow({ public_id: 'f', name: 'F' })
    const r = makeUnitRow({ public_id: 'r', kind: 'rack', name: 'R', parent: 'f' })
    const b = makeUnitRow({ public_id: 'b', kind: 'box', name: 'B', parent: 'r', rows: 9, cols: 9 })
    const out = makeUnitRow({ public_id: 'o', kind: 'ln2_tank', name: 'Old', status: 'out_of_service' })
    const r2 = makeUnitRow({ public_id: 'r2', kind: 'rack', name: 'R2', parent: 'f' })
    const rows = [f, r, b, out, r2]
    expect(moveTargets({ kind: 'rack' }, rows)).toEqual([{ value: 'f', label: 'F' }])
    expect(moveTargets({ kind: 'box' }, rows).map((t) => t.label)).toEqual(['F', 'F / R', 'F / R2'])
  })
})
