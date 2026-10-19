import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeUnitRow, problem } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { StorageTree } from './StorageTree'
import { UnitTree } from './UnitTree'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const TREE = '/api/v1/labs/{lab_public_id}/storage-units/'
const freezer = makeUnitRow({ public_id: '00000000-0000-4000-8000-0000000000f1', name: 'Freezer A', temperature_c: -80 })
const rack = makeUnitRow({ public_id: '00000000-0000-4000-8000-0000000000a1', kind: 'rack', name: 'Rack 1', parent: freezer.public_id, slot: 1, max_risk_group: null })
const box = makeUnitRow({ public_id: '00000000-0000-4000-8000-0000000000b1', kind: 'box', name: 'Box 1', parent: rack.public_id, slot: 1, rows: 9, cols: 9, max_risk_group: null })
const tank = makeUnitRow({ public_id: '00000000-0000-4000-8000-0000000000f2', kind: 'ln2_tank', name: 'Tank B', status: 'out_of_service', path_active: false })
const ROWS = [freezer, rack, box, tank]

async function render(onOpen = vi.fn<(unitId: string) => void>()) {
  await renderWithProviders(<StorageTree label="Storage of Mycology" rows={ROWS} onOpen={onOpen} />)
  return { onOpen, tree: screen.getByRole('tree', { name: 'Storage of Mycology' }) }
}

const item = (name: RegExp) => screen.getByRole('treeitem', { name })

describe('StorageTree', () => {
  it('shows the roots open, each unit named by its kind, slot, size and status', async () => {
    const { tree } = await render()
    expect(tree).toHaveAccessibleDescription('Arrow keys move through the units and open or close them, Enter shows a unit.')
    const items = within(tree).getAllByRole('treeitem')
    // Freezer A open, so Rack 1 shows; Rack 1 closed, so Box 1 does not; the tank has no children.
    const names = items.map((el) => document.getElementById(el.getAttribute('aria-labelledby') ?? '')?.textContent)
    expect(names).toEqual(['Freezer A, freezer, -80\u00a0°C', 'Rack 1, rack in slot 1', 'Tank B, LN2 tank, out of service'])
    expect(item(/^Freezer A/)).toHaveAccessibleName('Freezer A, freezer, -80\u00a0°C')
    expect(item(/^Freezer A/)).toHaveAttribute('aria-expanded', 'true')
    expect(item(/^Rack 1/)).toHaveAttribute('aria-expanded', 'false')
    expect(item(/^Tank B/)).not.toHaveAttribute('aria-expanded')
    expect(item(/^Rack 1/)).toHaveAttribute('aria-level', '2')
    expect(item(/^Tank B/)).toHaveAttribute('aria-posinset', '2')
    expect(item(/^Tank B/)).toHaveAttribute('aria-setsize', '2')
    expect(within(item(/^Freezer A/)).getByRole('group', { name: 'In freezer Freezer A' })).toContainElement(item(/^Rack 1/))
  })

  it('is one tab stop, and the arrow keys move, open and close', async () => {
    const { onOpen } = await render()
    const user = userEvent.setup()
    await user.tab()
    expect(item(/^Freezer A/)).toHaveFocus()
    expect(screen.getAllByRole('treeitem').filter((el) => el.tabIndex === 0)).toHaveLength(1)
    await user.keyboard('{ArrowDown}')
    expect(item(/^Rack 1/)).toHaveFocus()
    expect(item(/^Rack 1/)).toHaveAttribute('tabindex', '0')
    expect(item(/^Freezer A/)).toHaveAttribute('tabindex', '-1')
    await user.keyboard('{ArrowRight}')
    expect(item(/^Rack 1/)).toHaveAttribute('aria-expanded', 'true')
    expect(item(/^Box 1/)).toBeInTheDocument()
    expect(item(/^Box 1/)).toHaveAccessibleName('Box 1, box in slot 1, 9 x 9')
    await user.keyboard('{ArrowRight}')
    expect(item(/^Box 1/)).toHaveFocus()
    await user.keyboard('{ArrowLeft}{ArrowLeft}')
    expect(item(/^Rack 1/)).toHaveFocus()
    expect(screen.queryByRole('treeitem', { name: /^Box 1/ })).not.toBeInTheDocument()
    await user.keyboard('{End}')
    expect(item(/^Tank B/)).toHaveFocus()
    await user.keyboard('{Home}')
    expect(item(/^Freezer A/)).toHaveFocus()
    await user.keyboard('t')
    expect(item(/^Tank B/)).toHaveFocus()
    await user.tab()
    expect(document.body).toHaveFocus() // one tab stop: Tab leaves the tree
    expect(onOpen).not.toHaveBeenCalled()
  })

  it('shows the focused unit on Enter', async () => {
    const { onOpen } = await render()
    const user = userEvent.setup()
    await user.tab()
    await user.keyboard('{ArrowDown}{Enter}')
    expect(onOpen).toHaveBeenCalledWith(rack.public_id)
  })

  it('opens a unit on a click on its name, and opens or closes it on a click on the arrow', async () => {
    const { onOpen } = await render()
    const user = userEvent.setup()
    const toggle = item(/^Rack 1/).querySelector('[data-toggle]')
    expect(toggle).toHaveAttribute('aria-hidden', 'true')
    if (!(toggle instanceof HTMLElement)) throw new Error('no toggle')
    await user.click(toggle)
    expect(item(/^Rack 1/)).toHaveAttribute('aria-expanded', 'true')
    expect(onOpen).not.toHaveBeenCalled()
    await user.click(screen.getByText('Box 1'))
    expect(onOpen).toHaveBeenCalledTimes(1)
    expect(onOpen).toHaveBeenCalledWith(box.public_id) // only the innermost item handles the click
  })
})

describe('UnitTree', () => {
  it('loads the tree, then shows it', async () => {
    mockApi('get', TREE, ROWS)
    await renderWithProviders(<UnitTree labId={LAB_ID} labName="Mycology" canManage onOpen={vi.fn<(unitId: string) => void>()} />)
    expect(screen.getByText('Loading the storage…')).toBeInTheDocument()
    expect(await screen.findByRole('tree', { name: 'Storage of Mycology' })).toBeInTheDocument()
  })

  it.each([
    [true, 'No storage yet. Start with a freezer or an LN2 tank.'],
    [false, 'No storage yet. Curators and managers add freezers and tanks.'],
  ])('says when the lab has no storage (may manage: %s)', async (canManage, text) => {
    mockApi('get', TREE, [])
    await renderWithProviders(<UnitTree labId={LAB_ID} labName="Mycology" canManage={canManage} onOpen={vi.fn<(unitId: string) => void>()} />)
    expect(await screen.findByText(text)).toBeInTheDocument()
  })

  it('shows a failed load with a retry that works', async () => {
    allowConsole(/API error 500/)
    mockApiError('get', TREE, 500, problem(500))
    await renderWithProviders(<UnitTree labId={LAB_ID} labName="Mycology" canManage onOpen={vi.fn<(unitId: string) => void>()} />)
    expect(await screen.findByText(/Could not load the storage/)).toBeInTheDocument()
    mockApi('get', TREE, ROWS)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('tree')).toBeInTheDocument()
  })
})
