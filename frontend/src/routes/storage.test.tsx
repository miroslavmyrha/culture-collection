import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { makeBoxGrid, makeLab, makeMe, makeUnit, makeUnitRow } from '@/test/factories'
import { mockApi } from '@/test/mockApi'
import { renderApp } from '@/test/render'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const TREE = '/api/v1/labs/{lab_public_id}/storage-units/'
const UNIT = '/api/v1/labs/{lab_public_id}/storage-units/{public_id}/'
const signedIn = () => mockApi('get', '/api/v1/auth/me/', makeMe())
const lab = (role: 'viewer' | 'technician' | 'curator' | 'manager') => mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: role }))
const freezer = makeUnitRow({ public_id: '00000000-0000-4000-8000-0000000000f1', name: 'Freezer A', temperature_c: -80 })

describe('/labs/$labId/storage route', { timeout: 20_000 }, () => {
  it('loads the lab and the tree once, before the page renders', async () => {
    signedIn()
    lab('viewer')
    const calls = mockApi('get', TREE, [freezer])
    renderApp({ path: `/labs/${LAB_ID}/storage` })
    expect(await screen.findByRole('heading', { level: 1, name: 'Storage of Mycology' }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByRole('tree', { name: 'Storage of Mycology' })).toBeInTheDocument() // no loading state: the loader filled the cache
    expect(calls).toHaveLength(1)
    // A viewer reads; adding is for curators and managers.
    expect(screen.queryByRole('button', { name: 'Add a freezer or tank' })).not.toBeInTheDocument()
  })

  it('opens a unit from the tree by keyboard', async () => {
    signedIn()
    lab('viewer')
    mockApi('get', TREE, [freezer])
    mockApi('get', UNIT, makeUnit({ ...freezer }))
    const { router } = renderApp({ path: `/labs/${LAB_ID}/storage` })
    const user = userEvent.setup()
    const item = await screen.findByRole('treeitem', { name: /^Freezer A/ }, { timeout: 5000 })
    item.focus()
    await user.keyboard('{Enter}')
    await waitFor(() => expect(router.state.location.pathname).toBe(`/labs/${LAB_ID}/storage/${freezer.public_id}`))
    expect(await screen.findByRole('heading', { level: 1, name: 'Freezer A' })).toBeInTheDocument()
  })

  it('lets a curator add a freezer, then shows it', async () => {
    signedIn()
    lab('curator')
    mockApi('get', TREE, [])
    const created = makeUnit({ public_id: '00000000-0000-4000-8000-0000000000f9', name: 'Freezer C', temperature_c: -80, max_risk_group: 2 })
    const calls = mockApi('post', TREE, created)
    mockApi('get', UNIT, created)
    const { router } = renderApp({ path: `/labs/${LAB_ID}/storage` })
    const user = userEvent.setup()
    expect(await screen.findByText('No storage yet. Start with a freezer or an LN2 tank.', {}, { timeout: 5000 })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add a freezer or tank' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add a freezer or tank' })
    const kind = within(dialog).getByRole('combobox', { name: 'Kind' })
    await waitFor(() => expect(kind).toHaveFocus())
    expect(within(kind).getAllByRole('option').map((o) => o.textContent)).toEqual(['Freezer', 'LN2 tank'])
    await user.type(within(dialog).getByRole('textbox', { name: 'Name' }), 'Freezer C')
    await user.type(within(dialog).getByRole('textbox', { name: 'Temperature (°C)' }), '-80')
    // A root states its cap: the form asks before any request.
    await user.click(within(dialog).getByRole('button', { name: 'Add' }))
    const cap = within(dialog).getByRole('combobox', { name: 'Highest risk group' })
    await waitFor(() => expect(cap).toHaveFocus())
    expect(cap).toHaveAccessibleDescription(/states the highest risk group it may hold/)
    expect(calls).toHaveLength(0)
    expect(within(dialog).queryByRole('textbox', { name: 'Slot' })).not.toBeInTheDocument()
    await user.selectOptions(cap, '2')
    await user.click(within(dialog).getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(router.state.location.pathname).toBe(`/labs/${LAB_ID}/storage/${created.public_id}`))
    expect(calls[0]?.body).toEqual({ kind: 'freezer', parent: null, slot: null, name: 'Freezer C', barcode: '', temperature_c: -80, max_risk_group: 2, box_type: null })
    expect(await screen.findByRole('heading', { level: 1, name: 'Freezer C' })).toBeInTheDocument()
  })

  it('adds no freezer with the last valid temperature while the field shows an invalid one (#111)', async () => {
    signedIn()
    lab('curator')
    mockApi('get', TREE, [])
    const calls = mockApi('post', TREE, makeUnit({ name: 'Freezer C' }))
    renderApp({ path: `/labs/${LAB_ID}/storage` })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Add a freezer or tank' }, { timeout: 5000 }))
    const dialog = await screen.findByRole('dialog', { name: 'Add a freezer or tank' })
    await user.type(within(dialog).getByRole('textbox', { name: 'Name' }), 'Freezer C')
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Highest risk group' }), '2')
    const temperature = within(dialog).getByRole('textbox', { name: 'Temperature (°C)' })
    await user.type(temperature, '-80')
    for (const typed of ['-80x', '-80.5', '-80,5', '-274', '101']) {
      await user.clear(temperature)
      await user.type(temperature, typed)
      await user.click(within(dialog).getByRole('button', { name: 'Add' }))
      await waitFor(() => expect(temperature).toHaveAccessibleDescription(expect.stringContaining('Enter whole degrees from -273 to 100')))
      expect(temperature).toHaveValue(typed)
      expect(calls).toHaveLength(0)
    }
  })

  // The page composes the storage unit with the vials' grid: who may move vials is decided here.
  it.each([
    ['viewer', true, false],
    ['technician', true, true],
    ['manager', true, true],
    ['technician', false, false],
  ] as const)('a box for a %s (active %s) shows its positions, with bench work: %s', async (role, active, bench) => {
    signedIn()
    lab(role)
    const box = makeUnit({ public_id: '00000000-0000-4000-8000-0000000000b1', kind: 'box', name: 'Box 1', rows: 9, cols: 9, path_active: active })
    mockApi('get', UNIT, box)
    mockApi('get', '/api/v1/labs/{lab_public_id}/boxes/{public_id}/', makeBoxGrid({ public_id: box.public_id }))
    renderApp({ path: `/labs/${LAB_ID}/storage/${box.public_id}` })
    const grid = await screen.findByRole('grid', { name: 'Positions of Box 1' }, { timeout: 5000 })
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(grid.hasAttribute('aria-readonly')).toBe(!bench)
    expect(screen.queryByRole('form', { name: 'Place a vial' }) !== null).toBe(bench)
  })

  it('a unit that is no box has no positions and asks for none', async () => {
    signedIn()
    lab('manager')
    mockApi('get', UNIT, makeUnit({ ...freezer }))
    renderApp({ path: `/labs/${LAB_ID}/storage/${freezer.public_id}` })
    expect(await screen.findByRole('heading', { level: 1, name: 'Freezer A' }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByRole('grid')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Positions' })).not.toBeInTheDocument()
  })
})
