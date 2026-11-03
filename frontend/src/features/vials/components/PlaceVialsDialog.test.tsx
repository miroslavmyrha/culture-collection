import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { preferences } from '@/lib/storage'
import { allowConsole } from '@/test/console'
import { makeBoxGrid, makeBoxVial, makePosition, makeVial, problem, validationProblem } from '@/test/factories'
import { holdApi, mockApi, mockApiError } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import type { BoxChoice, Vial } from '../schemas'
import { lastBoxKey, PlaceVialsDialog } from './PlaceVialsDialog'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const STRAIN_ID = '00000000-0000-4000-8000-0000000000d1'
const BOX = '/api/v1/labs/{lab_public_id}/boxes/{public_id}/'
const PLACE = '/api/v1/labs/{lab_public_id}/boxes/{public_id}/place/'
const ONE: BoxChoice = { public_id: '00000000-0000-4000-8000-0000000000b1', label: 'Freezer A / Rack 1 / Box 1', rows: 3, cols: 3, free: 7 }
const TWO: BoxChoice = { public_id: '00000000-0000-4000-8000-0000000000b2', label: 'Freezer A / Rack 1 / Box 2', rows: 3, cols: 3, free: 9 }
// Fixed ids: the factory counter starts again in every test.
const a = makeVial({ public_id: '00000000-0000-4000-8000-0000000000f1', label: 'MYC 42 / 2 / 1' })
const b = makeVial({ public_id: '00000000-0000-4000-8000-0000000000f2', label: 'MYC 42 / 2 / 2' })
const c = makeVial({ public_id: '00000000-0000-4000-8000-0000000000f3', label: 'MYC 42 / 2 / 3' })
/** Box 1, 3 x 3: A1 holds a vial of MYC 42, A3 one of a regulated strain (no vial sent). */
const grid = makeBoxGrid({ public_id: ONE.public_id, rows: 3, cols: 3, positions: [makePosition('A1', makeBoxVial({ label: 'MYC 42 / 1 / 1' })), makePosition('A3', 'masked')] })

const placed = (vials: readonly Vial[], masked = false) => ({ vials: vials.map((v) => ({ ...v, placed: true, location_masked: masked })) })

async function render(vials: readonly Vial[] = [a, b, c], { boxes = [ONE, TWO] as BoxChoice[] | undefined, onClose = vi.fn<() => void>() } = {}) {
  const view = await renderWithProviders(
    <PlaceVialsDialog labId={LAB_ID} strainId={STRAIN_ID} vials={vials} boxes={boxes} boxesFailed={false} open onClose={onClose} onExited={() => undefined} />,
  )
  return { view, onClose }
}

const dialog = () => screen.getByRole('dialog', { name: /^Place \d+ vials? in a box$/ })
const positions = () => screen.getByRole('grid', { name: 'Free positions of Freezer A / Rack 1 / Box 1' })
const plan = () => within(screen.getByRole('list', { name: 'Where each vial goes' })).getAllByRole('listitem').map((li) => li.textContent)

async function chooseBoxOne(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(await within(dialog()).findByRole('combobox', { name: 'Box' }), ONE.public_id)
  await screen.findByRole('grid', { name: 'Free positions of Freezer A / Rack 1 / Box 1' })
}

describe('PlaceVialsDialog', () => {
  afterEach(() => vi.restoreAllMocks())

  it('shows the free positions of the chosen box and plans each vial into the next one, row by row', async () => {
    mockApi('get', BOX, grid)
    const calls = mockApi('post', PLACE, placed([a, b, c]))
    const { onClose } = await render()
    const user = userEvent.setup()
    // Each box says how many positions it has free before it is chosen (#80, walkthrough T3).
    const boxes = await within(dialog()).findByRole('combobox', { name: 'Box' })
    expect(within(boxes).getAllByRole('option').map((o) => o.textContent)).toEqual(['Choose', 'Freezer A / Rack 1 / Box 1, 7 free', 'Freezer A / Rack 1 / Box 2, 9 free'])
    await chooseBoxOne(user)
    expect(screen.getByText('7 of 9 positions free.')).toBeInTheDocument()
    // Taken says only taken, a regulated vial's place too.
    expect(within(positions()).getByRole('gridcell', { name: 'A1, taken' })).toHaveAttribute('aria-disabled', 'true')
    expect(within(positions()).getByRole('gridcell', { name: 'A3, taken' })).toHaveTextContent(/^Taken$/)
    expect(plan()).toEqual(['MYC 42 / 2 / 1: A2', 'MYC 42 / 2 / 2: B1', 'MYC 42 / 2 / 3: B2'])
    await user.click(within(dialog()).getByRole('button', { name: 'Place vials' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(calls[0]?.body).toEqual({
      placements: [
        { vial: a.public_id, row: 1, col: 2 },
        { vial: b.public_id, row: 2, col: 1 },
        { vial: c.public_id, row: 2, col: 2 },
      ],
    })
  })

  it('puts a picked vial on a chosen free position by keyboard; the others move on in order', async () => {
    mockApi('get', BOX, grid)
    const calls = mockApi('post', PLACE, placed([a, b, c]))
    await render()
    const user = userEvent.setup()
    await chooseBoxOne(user)
    await user.selectOptions(within(dialog()).getByRole('combobox', { name: 'Vial to place on the grid' }), 'MYC 42 / 2 / 3')
    within(positions()).getByRole('gridcell', { name: 'A1, taken' }).focus()
    await user.keyboard('{ArrowDown}{ArrowDown}{ArrowRight}{ArrowRight}{Enter}') // C3
    expect(screen.getByRole('status')).toHaveTextContent('MYC 42 / 2 / 3 goes to C3.')
    expect(plan()).toEqual(['MYC 42 / 2 / 1: A2', 'MYC 42 / 2 / 2: B1', 'MYC 42 / 2 / 3: C3, chosen'])
    // The next vial is the first again: A2 is only planned by order, so the pick takes it.
    await user.keyboard('{ArrowUp}{ArrowUp}{ArrowLeft}{Enter}') // A2 for MYC 42 / 2 / 1 stays its own
    expect(plan()[0]).toBe('MYC 42 / 2 / 1: A2, chosen')
    // A taken position is refused with the same words for any vial.
    await user.keyboard('{ArrowRight}{Enter}')
    expect(screen.getByRole('status')).toHaveTextContent('Another vial is in this position. Choose another one.')
    await user.click(within(dialog()).getByRole('button', { name: 'Next free positions' }))
    expect(plan()).toEqual(['MYC 42 / 2 / 1: A2', 'MYC 42 / 2 / 2: B1', 'MYC 42 / 2 / 3: B2'])
    await user.click(within(dialog()).getByRole('button', { name: 'Place vials' }))
    await waitFor(() => expect(calls).toHaveLength(1))
  })

  it('names the vial a refusal is about, from the index the server sends, and shows the position as taken', async () => {
    allowConsole(/API error 409/)
    mockApi('get', BOX, grid)
    mockApiError('post', PLACE, 409, problem(409, { code: 'position_taken', detail: 'x', errors: [{ attr: 'placements.1', code: 'position_taken', detail: 'x' }] }))
    await render()
    const user = userEvent.setup()
    await chooseBoxOne(user)
    const fresh = mockApi('get', BOX, { ...grid, positions: [...grid.positions, makePosition('B1', 'masked')] })
    await user.click(within(dialog()).getByRole('button', { name: 'Place vials' }))
    expect(await within(dialog()).findByRole('alert')).toHaveTextContent('Vial MYC 42 / 2 / 2: Another vial is in this position. Choose another one.')
    expect(dialog()).toHaveAccessibleDescription(/Vial MYC 42 \/ 2 \/ 2: Another vial/)
    await waitFor(() => expect(fresh).toHaveLength(1))
    // The plan moves the refused vial around the taken position, so its line drops the refusal;
    // the dialog's message still says what happened.
    await waitFor(() => expect(plan()).toEqual(['MYC 42 / 2 / 1: A2', 'MYC 42 / 2 / 2: B2', 'MYC 42 / 2 / 3: B3']))
    expect(within(dialog()).getByRole('alert')).toHaveTextContent('Vial MYC 42 / 2 / 2: Another vial')
  })

  it.each([
    [400, validationProblem([{ attr: 'placements.2.vial', code: 'risk_group_above_cap', detail: 'x' }]), "Vial MYC 42 / 2 / 3: This box may not hold this strain's risk group."],
    [409, problem(409, { code: 'vial_already_placed', errors: [{ attr: 'placements.0.vial', code: 'vial_already_placed', detail: 'x' }] }), 'Vial MYC 42 / 2 / 1: This vial is in a box already. Move it from its own row.'],
    [400, problem(400, { code: 'unit_not_active', detail: 'x' }), 'This box or a unit holding it is out of service or retired.'],
  ])('maps a %i refusal to its words (%#)', async (status, body, text) => {
    allowConsole(new RegExp(`API error ${status}`))
    mockApi('get', BOX, grid)
    mockApiError('post', PLACE, status, body)
    await render()
    const user = userEvent.setup()
    await chooseBoxOne(user)
    await user.click(within(dialog()).getByRole('button', { name: 'Place vials' }))
    expect(await within(dialog()).findByRole('alert')).toHaveTextContent(text)
  })

  it.each([
    [400, validationProblem([{ attr: 'placements.2.vial', code: 'risk_group_above_cap', detail: 'x' }]), 'MYC 42 / 2 / 3', "This box may not hold this strain's risk group."],
    [409, problem(409, { code: 'vial_already_placed', errors: [{ attr: 'placements.0.vial', code: 'vial_already_placed', detail: 'x' }] }), 'MYC 42 / 2 / 1', 'This vial is in a box already. Move it from its own row.'],
  ])('keeps a %i refusal that is not about the position on its vial\'s line (%#)', async (status, body, label, text) => {
    allowConsole(new RegExp(`API error ${status}`))
    mockApi('get', BOX, grid)
    mockApiError('post', PLACE, status, body)
    await render()
    const user = userEvent.setup()
    await chooseBoxOne(user)
    await user.click(within(dialog()).getByRole('button', { name: 'Place vials' }))
    await within(dialog()).findByRole('alert')
    expect(plan().find((line) => line.startsWith(`${label}: `))).toContain(text)
  })

  it('sends one request while the placement runs, whatever is pressed', async () => {
    mockApi('get', BOX, grid)
    const held = holdApi('post', PLACE)
    const { onClose } = await render()
    const user = userEvent.setup()
    await chooseBoxOne(user)
    const confirm = within(dialog()).getByRole('button', { name: 'Place vials' })
    await user.click(confirm)
    await user.click(confirm)
    await user.keyboard('{Escape}')
    expect(held.calls).toHaveLength(1)
    expect(confirm).toHaveAttribute('aria-disabled', 'true')
    held.release(200, placed([a, b, c]))
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
    expect(held.calls).toHaveLength(1)
  })

  it('refuses a box with too few free positions before it asks the server', async () => {
    mockApi('get', BOX, { ...grid, positions: ['A1', 'A2', 'A3', 'B1', 'B2', 'B3', 'C1'].map((p) => makePosition(p, 'masked')) })
    const held = holdApi('post', PLACE)
    await render()
    const user = userEvent.setup()
    await chooseBoxOne(user)
    expect(plan()).toEqual(['MYC 42 / 2 / 1: C2', 'MYC 42 / 2 / 2: C3', 'MYC 42 / 2 / 3: no free position'])
    await user.click(within(dialog()).getByRole('button', { name: 'Place vials' }))
    expect(within(dialog()).getByRole('alert')).toHaveTextContent('This box has 2 free positions for 3 vials. Choose another box.')
    expect(held.calls).toEqual([])
  })

  it('remembers the box for the next time, per lab, and opens on it', async () => {
    mockApi('get', BOX, grid)
    mockApi('post', PLACE, placed([a]))
    const first = await render([a])
    const user = userEvent.setup()
    await chooseBoxOne(user)
    await user.click(within(dialog()).getByRole('button', { name: 'Place vial' }))
    await waitFor(() => expect(first.onClose).toHaveBeenCalled())
    expect(preferences.get(lastBoxKey(LAB_ID))).toBe(ONE.public_id)
    first.view.unmount()
    await render([b])
    expect(await screen.findByRole('combobox', { name: 'Box' })).toHaveValue(ONE.public_id)
    expect(await screen.findByRole('grid', { name: 'Free positions of Freezer A / Rack 1 / Box 1' })).toBeInTheDocument()
  })

  it('does not remember a box that took a vial of a regulated strain', async () => {
    mockApi('get', BOX, grid)
    mockApi('post', PLACE, placed([a], true))
    const { onClose } = await render([a])
    const user = userEvent.setup()
    await chooseBoxOne(user)
    await user.click(within(dialog()).getByRole('button', { name: 'Place vial' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(preferences.get(lastBoxKey(LAB_ID))).toBeNull()
  })

  it('opens without a box when the remembered one is not offered any more', async () => {
    preferences.set(lastBoxKey(LAB_ID), '00000000-0000-4000-8000-0000000000b9')
    await render([a])
    expect(await screen.findByRole('combobox', { name: 'Box' })).toHaveValue('')
  })

  it('works without storage: nothing remembered, nothing breaks', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError')
    })
    const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError')
    })
    mockApi('get', BOX, grid)
    const calls = mockApi('post', PLACE, placed([a]))
    const { onClose } = await render([a])
    const user = userEvent.setup()
    expect(await screen.findByRole('combobox', { name: 'Box' })).toHaveValue('')
    await chooseBoxOne(user)
    await user.click(within(dialog()).getByRole('button', { name: 'Place vial' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(calls).toHaveLength(1)
    expect(set).toHaveBeenCalled()
  })
})
