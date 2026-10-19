import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { allowConsole } from '@/test/console'
import { type BoxGrid, makeBoxGrid, makeBoxVial, makePosition, makeVial, page, problem } from '@/test/factories'
import { holdApi, mockApi, mockApiError, recordRequests } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { vialKeys } from '../api/keys'
import { BoxPositions } from './BoxPositions'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const BOX_ID = '00000000-0000-4000-8000-0000000000b1'
const BOX = '/api/v1/labs/{lab_public_id}/boxes/{public_id}/'
const PLACE = '/api/v1/labs/{lab_public_id}/vials/{public_id}/place/'
const VIALS = '/api/v1/labs/{lab_public_id}/vials/'

// Fixed ids: the factory counter starts again in every test, so a vial made inside a test would get these.
const first = makeBoxVial({ public_id: '00000000-0000-4000-8000-0000000000f1', label: 'MYC 42 / 1 / 1' })
const second = makeBoxVial({ public_id: '00000000-0000-4000-8000-0000000000f2', label: 'MYC 42 / 1 / 2', status: 'quarantined' })
/** B3 and B4 hold vials of MYC 42, C4 a vial of a regulated strain: the API sent no vial for it. */
const FULL = makeBoxGrid({
  public_id: BOX_ID,
  positions: [makePosition('B3', first), makePosition('B4', second), makePosition('C4', 'masked')],
})
const after = (grid: BoxGrid, positions: BoxGrid['positions']): BoxGrid => ({ ...grid, positions })

const render = (canHandle = true) => renderWithProviders(<BoxPositions labId={LAB_ID} boxId={BOX_ID} boxName="Box 1" canHandle={canHandle} />)
const grid = () => screen.getByRole('grid', { name: 'Positions of Box 1' })
const cell = (name: string | RegExp) => within(grid()).getByRole('gridcell', { name })
const status = () => screen.getByRole('status')
const selected = () => [...grid().querySelectorAll('[aria-selected="true"]')].map((c) => c.getAttribute('data-pos'))

/** Focus the grid's tab stop the way Tab does, then walk with keys. */
async function enterGrid(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByRole('grid', { name: 'Positions of Box 1' })
  cell('A1, empty').focus()
  return user
}

describe('BoxPositions', { timeout: 20_000 }, () => {
  it('names every position, empty, taken with the label and the state, and masked without anything', async () => {
    mockApi('get', BOX, FULL)
    await render()
    await screen.findByRole('grid', { name: 'Positions of Box 1' })
    expect(within(grid()).getAllByRole('gridcell')).toHaveLength(81)
    expect(cell('A1, empty')).toHaveAttribute('tabindex', '0')
    expect(cell('B3, MYC 42 / 1 / 1, available')).toHaveTextContent('MYC 421 / 1')
    expect(cell('B4, MYC 42 / 1 / 2, quarantined')).toHaveTextContent('MYC 421 / 2quarantined')
    const masked = cell('C4, occupied, regulated')
    expect(masked).toHaveTextContent(/^Hidden$/)
    expect(masked).toHaveAttribute('data-tone', 'masked')
    // A grid holds no link; the strain's link is in the details of the focused position.
    expect(within(grid()).queryAllByRole('link')).toEqual([])
    expect(grid().querySelectorAll('[tabindex="0"]')).toHaveLength(1)
  })

  it('shows the focused position in words with its strain, and a masked one without', async () => {
    mockApi('get', BOX, FULL)
    await render()
    const user = await enterGrid(userEvent.setup())
    expect(screen.getByText('Position A1: empty.')).toBeInTheDocument()
    await user.keyboard('{ArrowDown}{ArrowRight}{ArrowRight}')
    expect(screen.getByText(/Position B3: MYC 42 \/ 1 \/ 1, available\./)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Strain MYC 42' })).toHaveAttribute('href', `/labs/${LAB_ID}/strains/${first.strain}`)
    await user.keyboard('{ArrowDown}{ArrowRight}')
    expect(screen.getByText('Position C4: a vial of a regulated strain. Which one is hidden.')).toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('a viewer reads a grid that selects nothing and changes nothing', async () => {
    mockApi('get', BOX, FULL)
    const posts = recordRequests('post', PLACE)
    await render(false)
    const user = await enterGrid(userEvent.setup())
    expect(grid()).toHaveAttribute('aria-readonly', 'true')
    expect(grid().querySelectorAll('[aria-selected], [aria-disabled]')).toHaveLength(0)
    expect(screen.queryByRole('form', { name: 'Place a vial' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    await user.keyboard('{ArrowDown}{ArrowRight}{ArrowRight}{Enter} ')
    expect(cell(/^B3,/)).toHaveFocus()
    await user.click(cell(/^B3,/))
    await user.keyboard('{ArrowRight}{ArrowRight}{ArrowRight}{Enter}')
    expect(screen.queryByRole('status')).not.toBeInTheDocument() // nothing to announce to a reader
    expect(posts).toHaveLength(0)
  })

  it('moves a vial in two steps by keyboard, says so once, and keeps the focus on the vial in its new position', async () => {
    mockApi('get', BOX, FULL)
    const calls = mockApi('post', PLACE, makeVial({ public_id: first.public_id, label: first.label, placed: true }), { status: 200 })
    await render()
    const user = await enterGrid(userEvent.setup())
    await user.keyboard('{ArrowDown}{ArrowRight}{ArrowRight}{Enter}')
    expect(selected()).toEqual(['B3'])
    expect(status()).toHaveTextContent('MYC 42 / 1 / 1 in B3 selected. Choose an empty position and press Enter, or Escape to cancel.')
    // While moving, a taken position is refused, an empty one is not.
    expect(cell(/^B4,/)).toHaveAttribute('aria-disabled', 'true')
    expect(cell('C4, occupied, regulated')).toHaveAttribute('aria-disabled', 'true')
    expect(cell('D5, empty')).not.toHaveAttribute('aria-disabled')
    mockApi('get', BOX, after(FULL, [makePosition('D5', first), makePosition('B4', second), makePosition('C4', 'masked')]))
    await user.keyboard('{ArrowDown}{ArrowDown}{ArrowRight}{ArrowRight}{Enter}')
    await waitFor(() => expect(status()).toHaveTextContent('MYC 42 / 1 / 1 moved to D5.'))
    expect(calls).toHaveLength(1)
    expect(calls[0]?.url.pathname).toBe(`/api/v1/labs/${LAB_ID}/vials/${first.public_id}/place/`)
    expect(calls[0]?.body).toEqual({ box: BOX_ID, row: 4, col: 5 })
    expect(calls[0]?.headers.get('X-CSRFToken')).toBeTruthy()
    expect(cell('D5, MYC 42 / 1 / 1, available')).toHaveFocus()
    expect(cell('B3, empty')).toBeInTheDocument()
    expect(selected()).toEqual([])
    expect(grid().querySelectorAll('[tabindex="0"]')).toHaveLength(1)
    expect(screen.getAllByRole('status')).toHaveLength(1)
  })

  // The strain page and other boxes show where vials are: a move here may change them (#64).
  it("a move marks the moved strain's material and every box grid stale", async () => {
    mockApi('get', BOX, FULL)
    mockApi('post', PLACE, makeVial({ public_id: first.public_id, label: first.label, placed: true }), { status: 200 })
    const { client } = await render()
    const material = vialKeys.vials(LAB_ID, first.strain)
    const source = vialKeys.box(LAB_ID, '00000000-0000-4000-8000-0000000000b9')
    client.setQueryData(material, page([]))
    client.setQueryData(source, makeBoxGrid())
    const user = await enterGrid(userEvent.setup())
    await user.keyboard('{ArrowDown}{ArrowRight}{ArrowRight}{Enter}{ArrowDown}{ArrowDown}{Enter}')
    await waitFor(() => expect(status()).toHaveTextContent('MYC 42 / 1 / 1 moved to D3.'))
    expect(client.getQueryState(material)?.isInvalidated).toBe(true)
    expect(client.getQueryState(source)?.isInvalidated).toBe(true)
  })

  it('Escape cancels the move and returns the focus to the vial', async () => {
    mockApi('get', BOX, FULL)
    const posts = recordRequests('post', PLACE)
    await render()
    const user = await enterGrid(userEvent.setup())
    await user.keyboard('{ArrowDown}{ArrowRight}{ArrowRight}{Enter}{PageDown}{End}')
    expect(cell('I9, empty')).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(status()).toHaveTextContent('Move cancelled.')
    expect(cell(/^B3,/)).toHaveFocus()
    expect(selected()).toEqual([])
    expect(posts).toHaveLength(0)
    // Enter on the selected vial again cancels too.
    await user.keyboard('{Enter}{Enter}')
    expect(selected()).toEqual([])
    expect(status()).toHaveTextContent('Move cancelled.')
  })

  it('Cancel move, for a mouse, puts the focus back on the vial', async () => {
    mockApi('get', BOX, FULL)
    await render()
    const user = userEvent.setup()
    await screen.findByRole('grid')
    await user.click(cell(/^B3,/))
    await user.click(screen.getByRole('button', { name: 'Cancel move' }))
    expect(cell(/^B3,/)).toHaveFocus()
    expect(screen.queryByRole('button', { name: 'Cancel move' })).not.toBeInTheDocument()
    expect(selected()).toEqual([])
  })

  it('refuses a taken target, masked or not, with the same words and no request', async () => {
    mockApi('get', BOX, FULL)
    const posts = recordRequests('post', PLACE)
    await render()
    const user = await enterGrid(userEvent.setup())
    await user.keyboard('{ArrowDown}{ArrowRight}{ArrowRight}{Enter}{ArrowRight}{Enter}')
    expect(status()).toHaveTextContent(/^Another vial is in this position\. Choose another one\.$/)
    await user.keyboard('{ArrowDown}{Enter}')
    expect(cell('C4, occupied, regulated')).toHaveFocus()
    expect(status()).toHaveTextContent(/^Another vial is in this position\. Choose another one\.$/)
    expect(posts).toHaveLength(0)
    expect(selected()).toEqual(['B3'])
  })

  it('a masked vial cannot be picked here', async () => {
    mockApi('get', BOX, FULL)
    await render()
    const user = userEvent.setup()
    await screen.findByRole('grid')
    expect(cell('C4, occupied, regulated')).toHaveAttribute('aria-disabled', 'true')
    await user.click(cell('C4, occupied, regulated'))
    expect(selected()).toEqual([])
    expect(status()).toHaveTextContent('C4 holds a vial of a regulated strain. Move it from its strain page.')
  })

  it('shows the server refusal, keeps the vial picked and the focus on the target', async () => {
    mockApi('get', BOX, FULL)
    mockApiError('post', PLACE, 409, problem(409, { code: 'position_taken', detail: 'Another vial is in this position.' }))
    await render()
    const user = await enterGrid(userEvent.setup())
    await user.keyboard('{ArrowDown}{ArrowRight}{ArrowRight}{Enter}{ArrowDown}{ArrowDown}{Enter}')
    await waitFor(() => expect(status()).toHaveTextContent(/^Another vial is in this position\. Choose another one\.$/))
    expect(cell('D3, empty')).toHaveFocus()
    expect(selected()).toEqual(['B3'])
  })

  it.each([
    ['unit_not_active', 'This box or a unit holding it is out of service or retired.'],
    ['risk_group_above_cap', "This box may not hold this strain's risk group."],
  ])('says what a %s refusal means in its own words', async (code, text) => {
    mockApi('get', BOX, FULL)
    mockApiError('post', PLACE, 400, problem(400, { code, detail: 'server text', errors: [{ attr: 'box', code, detail: 'server text' }] }))
    await render()
    const user = await enterGrid(userEvent.setup())
    await user.keyboard('{ArrowDown}{ArrowRight}{ArrowRight}{Enter}{ArrowDown}{ArrowDown}{Enter}')
    await waitFor(() => expect(status()).toHaveTextContent(text))
  })

  it('a click picks the vial and a click on an empty position places it', async () => {
    mockApi('get', BOX, FULL)
    const calls = mockApi('post', PLACE, makeVial({ public_id: first.public_id, label: first.label, placed: true }), { status: 200 })
    await render()
    const user = userEvent.setup()
    await screen.findByRole('grid')
    await user.click(cell(/^B3,/))
    expect(selected()).toEqual(['B3'])
    mockApi('get', BOX, after(FULL, [makePosition('A9', first), makePosition('B4', second), makePosition('C4', 'masked')]))
    await user.click(cell('A9, empty'))
    await waitFor(() => expect(status()).toHaveTextContent('MYC 42 / 1 / 1 moved to A9.'))
    expect(calls[0]?.body).toEqual({ box: BOX_ID, row: 1, col: 9 })
    expect(cell(/^A9, MYC 42/)).toHaveFocus()
  })

  it('sends one request while a move runs, whatever is pressed', async () => {
    mockApi('get', BOX, FULL)
    const held = holdApi('post', PLACE)
    const { client } = await render()
    const user = await enterGrid(userEvent.setup())
    await user.keyboard('{ArrowDown}{ArrowRight}{ArrowRight}{Enter}{ArrowDown}{Enter}')
    expect(client.isMutating()).toBe(1)
    await user.keyboard('{Enter}{ArrowRight}{Enter}')
    await user.click(cell('E7, empty'))
    expect(held.calls).toHaveLength(1)
    held.release(500, problem(500))
    await waitFor(() => expect(status()).toHaveTextContent('The server failed. Try again in a moment.'))
  })

  it('places a vial found by its barcode, starting at the first empty position', async () => {
    mockApi('get', BOX, FULL)
    const loose = makeVial({ label: 'MYC 42 / 2 / 5', barcode: 'TUBE-7' })
    const lookups = mockApi('get', VIALS, page([loose]))
    const calls = mockApi('post', PLACE, { ...loose, placed: true }, { status: 200 })
    await render()
    const user = userEvent.setup()
    // A scanner types the code and presses Enter.
    await user.type(await screen.findByRole('textbox', { name: 'Vial label or barcode' }), 'TUBE-7{Enter}')
    await waitFor(() => expect(cell('A1, empty')).toHaveFocus())
    expect(lookups[0]?.url.searchParams.get('code')).toBe('TUBE-7')
    expect(status()).toHaveTextContent('MYC 42 / 2 / 5 found. Choose an empty position and press Enter, or Escape to cancel.')
    expect(screen.getByRole('textbox', { name: 'Vial label or barcode' })).toHaveValue('')
    expect(selected()).toEqual([])
    mockApi('get', BOX, after(FULL, [...FULL.positions, makePosition('A2', makeBoxVial({ public_id: loose.public_id, label: loose.label }))]))
    await user.keyboard('{ArrowRight}{Enter}')
    await waitFor(() => expect(status()).toHaveTextContent('MYC 42 / 2 / 5 placed in A2.'))
    expect(calls[0]?.body).toEqual({ box: BOX_ID, row: 1, col: 2 })
    expect(cell(/^A2, MYC 42 \/ 2 \/ 5/)).toHaveFocus()
  })

  it('Escape after a find returns the focus to the code field', async () => {
    mockApi('get', BOX, FULL)
    mockApi('get', VIALS, page([makeVial({ label: 'MYC 42 / 2 / 5' })]))
    await render()
    const user = userEvent.setup()
    const field = await screen.findByRole('textbox', { name: 'Vial label or barcode' })
    await user.type(field, 'MYC 42 / 2 / 5{Enter}')
    await waitFor(() => expect(cell('A1, empty')).toHaveFocus())
    await user.keyboard('{Escape}')
    expect(field).toHaveFocus()
    expect(status()).toHaveTextContent('Move cancelled.')
  })

  it('a regulated vial found by its code is placed without its position on screen', async () => {
    mockApi('get', BOX, FULL)
    const regulated = makeVial({ label: 'MYC 7 / 1 / 1', barcode: 'REG-1' })
    mockApi('get', VIALS, page([regulated]))
    mockApi('post', PLACE, { ...regulated, placed: true, location: null, location_masked: true }, { status: 200 })
    await render()
    const user = userEvent.setup()
    await user.type(await screen.findByRole('textbox', { name: 'Vial label or barcode' }), 'REG-1{Enter}')
    await waitFor(() => expect(cell('A1, empty')).toHaveFocus())
    mockApi('get', BOX, after(FULL, [...FULL.positions, makePosition('A1', 'masked')]))
    await user.keyboard('{Enter}')
    await waitFor(() => expect(status()).toHaveTextContent('MYC 7 / 1 / 1 placed. Its position is hidden: the strain is regulated.'))
    expect(status()).not.toHaveTextContent('A1')
    expect(cell('A1, occupied, regulated')).toHaveFocus()
    expect(document.body).not.toHaveTextContent('MYC 7 / 1 / 1 placed in')
  })

  it.each([
    [[], 'No vial of this lab has this label or barcode.'],
    [[makeVial({ status: 'consumed' })], 'This vial has left the collection or is lost: it has no place.'],
    [[makeVial(), makeVial()], 'More than one vial has this code. Type the label instead.'],
  ])('refuses a find on the field, with the focus there (%#)', async (results, text) => {
    mockApi('get', BOX, FULL)
    mockApi('get', VIALS, page(results))
    await render()
    const user = userEvent.setup()
    const field = await screen.findByRole('textbox', { name: 'Vial label or barcode' })
    await user.type(field, 'X-1{Enter}')
    await waitFor(() => expect(field).toHaveAccessibleDescription(`Scan the tube, or type its label. ${text}`))
    expect(field).toHaveAttribute('aria-invalid', 'true')
    expect(field).toHaveFocus()
  })

  it('asks for a code before it searches', async () => {
    mockApi('get', BOX, FULL)
    const lookups = recordRequests('get', VIALS)
    await render()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Find' }))
    const field = screen.getByRole('textbox', { name: 'Vial label or barcode' })
    await waitFor(() => expect(field).toHaveFocus())
    expect(field).toHaveAccessibleDescription('Scan the tube, or type its label. Scan or type the label or barcode')
    expect(lookups).toHaveLength(0)
  })

  it('a full box refuses a found vial', async () => {
    mockApi('get', BOX, makeBoxGrid({ public_id: BOX_ID, rows: 1, cols: 1, positions: [makePosition('A1', first)] }))
    mockApi('get', VIALS, page([makeVial()]))
    await render()
    const user = userEvent.setup()
    const field = await screen.findByRole('textbox', { name: 'Vial label or barcode' })
    await user.type(field, 'X-1{Enter}')
    await waitFor(() => expect(field).toHaveAccessibleDescription('Scan the tube, or type its label. This box is full.'))
  })

  it('shows a failed load with a retry that works', async () => {
    allowConsole(/API error 500/)
    mockApiError('get', BOX, 500)
    await render()
    expect(await screen.findByText(/Could not load the positions/)).toBeInTheDocument()
    expect(screen.getByRole('status')).toBeInTheDocument() // the live region exists before any message
    mockApi('get', BOX, FULL)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('grid', { name: 'Positions of Box 1' })).toBeInTheDocument()
  })
})
