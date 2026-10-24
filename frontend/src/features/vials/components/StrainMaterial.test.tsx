import { screen, waitFor, within } from '@testing-library/react'
import type { QueryClient } from '@tanstack/react-query'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeBatch, makeBoxGrid, makePassage, makeUnitRow, makeVial, page, problem, validationProblem } from '@/test/factories'
import { holdApi, mockApi, mockApiError, recordRequests } from '@/test/mockApi'
import { vialAction } from '@/test/actions'
import { renderWithProviders } from '@/test/render'
import { vialKeys } from '../api/keys'
import type { VialPage } from '../schemas'
import { StrainMaterial } from './StrainMaterial'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const STRAIN_ID = '00000000-0000-4000-8000-0000000000d1'
const PASSAGES = '/api/v1/labs/{lab_public_id}/passages/'
const BATCHES = '/api/v1/labs/{lab_public_id}/batches/'
const VIALS = '/api/v1/labs/{lab_public_id}/vials/'
const UNITS = '/api/v1/labs/{lab_public_id}/storage-units/'
const REVEAL = '/api/v1/labs/{lab_public_id}/vials/{public_id}/reveal-location/'

const zero = makePassage({ number: 0 })
const one = makePassage({ number: 1, source_kind: 'passage', source_passage: zero.public_id, parent: zero.public_id })
const freezer = makeUnitRow({ name: 'Freezer A' })
const rack = makeUnitRow({ kind: 'rack', name: 'Rack 1', parent: freezer.public_id, max_risk_group: null })
const box = makeUnitRow({ kind: 'box', name: 'Box 1', parent: rack.public_id, rows: 3, cols: 4, max_risk_group: null })
const placed = makeVial({
  label: 'MYC 42 / 1 / 1',
  placed: true,
  location: { box: box.public_id, box_name: 'Box 1', path: ['Freezer A', 'Rack 1', 'Box 1'], row: 2, col: 3, label: 'B3' },
})
const loose = makeVial({ label: 'MYC 42 / 1 / 2' })
const consumed = makeVial({ label: 'MYC 42 / 1 / 3', status: 'consumed', status_changed_at: '2026-10-02T10:00:00Z' })

function mockMaterial(vials = [placed, loose, consumed]) {
  mockApi('get', PASSAGES, page([zero, one]))
  mockApi('get', BATCHES, page([makeBatch({ number: 1, vials_available: 2 })]))
  mockApi('get', VIALS, page(vials))
  mockApi('get', UNITS, [freezer, rack, box])
}

/** Vials number `from` to `to` of a strain with 200 in batch 1 and the rest in batch 2. */
const many = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, i) => makeVial({ label: `MYC 42 / ${from + i > 200 ? 2 : 1} / ${((from + i - 1) % 200) + 1}` }))

/** The tab as the page drives it: the page of the vials in the page's state (the URL there). */
function Material({ canHandle, limit = 50, vial }: { canHandle: boolean; limit?: number; vial?: string }) {
  const [vialPage, setVialPage] = useState<VialPage>({ limit, offset: 0, batch: undefined, vial })
  return <StrainMaterial labId={LAB_ID} strainId={STRAIN_ID} accession="MYC 42" canHandle={canHandle} canRelease={canHandle} vialPage={vialPage} onVialPage={(next) => setVialPage((current) => ({ ...current, ...next }))} />
}

const render = (canHandle = true, limit = 50) => renderWithProviders(<Material canHandle={canHandle} limit={limit} />)

describe('StrainMaterial', { timeout: 20_000 }, () => {
  it('shows the passages, the batches and where each vial is', async () => {
    mockMaterial()
    await render()
    const vials = await screen.findByRole('table', { name: 'Vials' })
    expect(within(vials).getAllByRole('row').slice(1).map((row) => within(row).getAllByRole('cell')[2]?.textContent)).toEqual([
      'Freezer A / Rack 1 / Box 1, B3',
      'Not placed',
      'Left the collection',
    ])
    // The passages as a tree from the deposit: passage 1 nested under passage 0.
    const tree = screen.getByRole('list', { name: 'Passages from the deposit' })
    const root = within(tree).getByRole('listitem', { name: 'Passage 0' })
    expect(root).toHaveTextContent(/^Passage 0As receivedSubculture/)
    const grown = within(root).getByRole('list', { name: 'Grown from passage 0' })
    expect(within(grown).getByRole('listitem', { name: 'Passage 1' })).toHaveTextContent(/^Passage 1Subculture of passage 0Subculture$/)
    const batches = screen.getByRole('table', { name: 'Batches' })
    expect(within(batches).getAllByRole('row')[1]).toHaveTextContent('10Frozen at -80 °C, 10 % glycerolDistribution stock2026-10-01Pending checkWaiting for a passed identity, purity and viability check.2 of 3Checks')
    for (const name of ['Batches', 'Vials']) expect(screen.getByRole('region', { name: `${name} table` })).toHaveAttribute('tabindex', '0')
    // A consumed vial has no place and no next state: no actions. The others have one menu each.
    const last = within(vials).getAllByRole('row')[3]
    expect(last && within(last).queryAllByRole('button')).toEqual([])
    expect(last).toHaveTextContent(/None$/)
    expect(within(vials).getAllByRole('button').map((b) => b.getAttribute('aria-label'))).toEqual(['Actions for vial MYC 42 / 1 / 1', 'Actions for vial MYC 42 / 1 / 2'])
    expect(screen.getByText('3 vials')).toBeInTheDocument()
  })

  it('pages the vials of a strain with more than 200, with the count of all of them (#72)', async () => {
    mockApi('get', PASSAGES, page([zero]))
    mockApi('get', BATCHES, page([makeBatch({ number: 1, vial_count_created: 200 }), makeBatch({ number: 2, vial_count_created: 30 })]))
    mockApi('get', UNITS, [freezer, rack, box])
    const first = mockApi('get', VIALS, page(many(1, 50), { count: 230 }))
    await render()
    const pager = await screen.findByRole('navigation', { name: 'Pages of the vials' })
    expect(screen.getByText('230 vials')).toBeInTheDocument()
    expect(pager).toHaveTextContent('1 to 50 of 230')
    expect(first[0]?.url.searchParams.get('limit')).toBe('50')
    expect(first[0]?.url.searchParams.get('offset')).toBe('0')
    // The last page: rows 201 to 230, batch 2 included, none dropped.
    const user = userEvent.setup()
    for (const offset of [50, 100, 150, 200]) {
      const next = holdApi('get', VIALS)
      await user.click(within(pager).getByRole('button', { name: 'Next' }))
      await waitFor(() => expect(next.calls).toHaveLength(1))
      expect(next.calls[0]?.url.searchParams.get('offset')).toBe(String(offset))
      next.release(200, page(many(offset + 1, Math.min(offset + 50, 230)), { count: 230 }))
      await waitFor(() => expect(pager).toHaveTextContent(`${offset + 1} to ${Math.min(offset + 50, 230)} of 230`))
    }
    const rows = within(screen.getByRole('table', { name: 'Vials' })).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(30)
    expect(rows[29]).toHaveTextContent('MYC 42 / 2 / 30')
    expect(within(pager).getByRole('button', { name: 'Next' })).toHaveAttribute('aria-disabled', 'true')
  })

  it('narrows the vials to one batch, from the first page, and says how many there are in all', async () => {
    const two = makeBatch({ number: 2, vial_count_created: 30 })
    mockApi('get', PASSAGES, page([zero]))
    mockApi('get', BATCHES, page([makeBatch({ number: 1, vial_count_created: 200 }), two]))
    mockApi('get', UNITS, [freezer, rack, box])
    mockApi('get', VIALS, page([placed], { count: 230 }))
    await render()
    await screen.findByText('230 vials')
    const narrowed = mockApi('get', VIALS, page([loose], { count: 30 }))
    await userEvent.setup().selectOptions(screen.getByRole('combobox', { name: 'Batch' }), two.public_id)
    expect(await screen.findByText('30 vials of batch 2, of 230 in all.')).toBeInTheDocument()
    expect(narrowed[0]?.url.searchParams.get('batch')).toBe(two.public_id)
    expect(narrowed[0]?.url.searchParams.get('offset')).toBe('0')
    expect(screen.getByRole('combobox', { name: 'Batch' })).toHaveFocus()
  })

  it('shows only the vial a search opened, until Show every vial, which leaves the focus on the Vials heading (#76)', async () => {
    mockApi('get', PASSAGES, page([zero]))
    mockApi('get', BATCHES, page([makeBatch({ number: 1 })]))
    mockApi('get', UNITS, [freezer, rack, box])
    const narrowed = mockApi('get', VIALS, page([placed]))
    await renderWithProviders(<Material canHandle vial={placed.public_id} />)
    const vials = await screen.findByRole('table', { name: 'Vials' })
    expect(within(vials).getAllByRole('row')).toHaveLength(2)
    expect(narrowed[0]?.url.searchParams.get('vial')).toBe(placed.public_id)
    expect(screen.getByText('Only the vial you searched for.')).toBeInTheDocument()
    const every = mockApi('get', VIALS, page([placed, loose, consumed]))
    await userEvent.setup().click(screen.getByRole('button', { name: 'Show every vial' }))
    expect(await screen.findByText('3 vials')).toBeInTheDocument()
    expect(every[0]?.url.searchParams.has('vial')).toBe(false)
    expect(screen.queryByText('Only the vial you searched for.')).toBeNull()
    expect(screen.getByRole('heading', { level: 2, name: 'Vials' })).toHaveFocus()
  })

  it('offers no bench work to a viewer and loads no boxes for one', async () => {
    mockMaterial()
    const boxes = recordRequests('get', UNITS)
    await render(false)
    await screen.findByRole('table', { name: 'Vials' })
    expect(screen.queryByRole('button', { name: 'Preserve a batch' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Subculture|Move|Place|Change the state|Revive|Actions/ })).not.toBeInTheDocument()
    expect(boxes).toHaveLength(0)
  })

  it('says when there is nothing yet, and shows a failed load with a retry', async () => {
    allowConsole(/API error 500/)
    mockApi('get', PASSAGES, page([]))
    mockApi('get', BATCHES, page([]))
    mockApiError('get', VIALS, 500)
    await render(false)
    expect(await screen.findByText('No passage yet. A strain gets passage 0 when its deposit is accepted.')).toBeInTheDocument()
    expect(screen.getByText('No batch preserved yet.')).toBeInTheDocument()
    expect(await screen.findByText(/Could not load the vials/)).toBeInTheDocument()
    mockApi('get', VIALS, page([]))
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('No vial yet.')).toBeInTheDocument()
  })

  it('preserves a batch into a box by keyboard and refreshes the lists', async () => {
    mockMaterial()
    const calls = mockApi('post', BATCHES, makeBatch({ number: 2 }))
    const reloads = recordRequests('get', BATCHES)
    await render()
    const user = userEvent.setup()
    const trigger = await screen.findByRole('button', { name: 'Preserve a batch' })
    trigger.focus()
    await user.keyboard('{Enter}')
    const dialog = await screen.findByRole('dialog', { name: 'Preserve a batch of MYC 42' })
    const passage = within(dialog).getByRole('combobox', { name: 'Passage' })
    await waitFor(() => expect(passage).toHaveFocus())
    expect(passage).toHaveValue(one.public_id) // the latest passage first
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Purpose' }), 'seed')
    await user.type(within(dialog).getByRole('textbox', { name: 'Protectant' }), ' 10 % glycerol ')
    await user.type(within(dialog).getByRole('textbox', { name: 'Number of vials' }), '5')
    const boxField = await within(dialog).findByRole('combobox', { name: 'Box' })
    expect(within(boxField).getAllByRole('option').map((o) => o.textContent)).toEqual(['Do not place them yet', 'Freezer A / Rack 1 / Box 1'])
    await user.selectOptions(boxField, box.public_id)
    await user.tab() // Cancel
    await user.tab()
    expect(within(dialog).getByRole('button', { name: 'Preserve batch' })).toHaveFocus()
    await user.keyboard('{Enter}')
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({
      passage: one.public_id,
      method: 'cryo_minus80',
      purpose: 'seed',
      cryoprotectant: '10 % glycerol',
      preserved_on: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      vial_count: 5,
      box: box.public_id,
    })
    expect(calls[0]?.headers.get('X-CSRFToken')).toBeTruthy()
    expect(reloads.length).toBeGreaterThan(0)
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('checks the batch form before sending, and puts a full box on the box field', async () => {
    mockMaterial()
    mockApiError('post', BATCHES, 400, validationProblem([{ attr: 'box', code: 'box_full', detail: 'This box has 1 free positions, the batch 5 vials.' }]))
    const held = recordRequests('post', BATCHES)
    await render()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Preserve a batch' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Preserve batch' }))
    const count = within(dialog).getByRole('textbox', { name: 'Number of vials' })
    expect(count).toHaveAccessibleDescription('1 to 200 Enter how many vials')
    expect(count).toHaveFocus()
    expect(held).toHaveLength(0)
    await user.type(count, '201')
    await user.click(within(dialog).getByRole('button', { name: 'Preserve batch' }))
    expect(count).toHaveAccessibleDescription('1 to 200 A batch has 1 to 200 vials')
    await user.clear(count)
    await user.type(count, '5')
    await user.selectOptions(await within(dialog).findByRole('combobox', { name: 'Box' }), box.public_id)
    await user.click(within(dialog).getByRole('button', { name: 'Preserve batch' }))
    const boxField = within(dialog).getByRole('combobox', { name: 'Box' })
    await waitFor(() => expect(boxField).toHaveAccessibleDescription(/This box has 1 free positions, the batch 5 vials\.$/))
    expect(boxField).toHaveFocus()
    expect(dialog).toBeInTheDocument()
  })

  it('moves a vial to a position chosen by box, row and column', async () => {
    mockMaterial()
    const calls = mockApi('post', '/api/v1/labs/{lab_public_id}/vials/{public_id}/place/', placed)
    await render()
    const user = userEvent.setup()
    await vialAction(user, 'MYC 42 / 1 / 1', 'Move')
    const dialog = await screen.findByRole('dialog', { name: 'Move vial MYC 42 / 1 / 1' })
    const boxField = await within(dialog).findByRole('combobox', { name: 'Box' })
    expect(boxField).toHaveValue(box.public_id) // where it is now
    const row = within(dialog).getByRole('combobox', { name: 'Row' })
    expect(row).toHaveValue('2')
    expect(within(row).getAllByRole('option').map((o) => o.textContent)).toEqual(['Choose', 'A', 'B', 'C'])
    await user.selectOptions(row, '3')
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Column' }), '4')
    await user.click(within(dialog).getByRole('button', { name: 'Move vial' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ box: box.public_id, row: 3, col: 4 })
  })

  // The box grids show where vials are: a write here may change any box (#64).
  it.each([
    ['move', 'Move vial MYC 42 / 1 / 1', 'Move vial', '/api/v1/labs/{lab_public_id}/vials/{public_id}/place/', 'Move'],
    ['state change', 'Change the state of vial MYC 42 / 1 / 1', 'Save state', '/api/v1/labs/{lab_public_id}/vials/{public_id}/status/', 'Change state'],
  ] as const)('a %s marks every box grid of the lab stale, not other strains', async (_, open, confirm, path, item) => {
    mockMaterial()
    mockApi('post', path, placed, { status: 200 })
    const { client } = await render()
    const here = vialKeys.box(LAB_ID, box.public_id)
    const elsewhere = vialKeys.box(LAB_ID, '00000000-0000-4000-8000-0000000000b9')
    const otherStrain = vialKeys.vialPage(LAB_ID, '00000000-0000-4000-8000-0000000000d9', { limit: 50, offset: 0, batch: undefined })
    client.setQueryData(here, makeBoxGrid())
    client.setQueryData(elsewhere, makeBoxGrid())
    client.setQueryData(otherStrain, page([]))
    const user = userEvent.setup()
    await vialAction(user, 'MYC 42 / 1 / 1', item)
    const dialog = await screen.findByRole('dialog', { name: open })
    if (confirm === 'Save state') {
      await user.selectOptions(within(dialog).getByRole('combobox', { name: 'New state' }), 'consumed')
      await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'used up')
    } else {
      await within(dialog).findByRole('combobox', { name: 'Box' })
      await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Row' }), '3')
    }
    await user.click(within(dialog).getByRole('button', { name: confirm }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(client.getQueryState(here)?.isInvalidated).toBe(true)
    expect(client.getQueryState(elsewhere)?.isInvalidated).toBe(true)
    expect(client.getQueryState(otherStrain)?.isInvalidated).toBe(false)
  })

  it('places a loose vial and says inside the dialog when the position is taken', async () => {
    mockMaterial()
    mockApiError('post', '/api/v1/labs/{lab_public_id}/vials/{public_id}/place/', 409, problem(409, { code: 'position_taken' }))
    await render()
    const user = userEvent.setup()
    await vialAction(user, 'MYC 42 / 1 / 2', 'Place')
    const dialog = await screen.findByRole('dialog', { name: 'Place vial MYC 42 / 1 / 2' })
    await user.click(within(dialog).getByRole('button', { name: 'Place vial' }))
    expect(within(dialog).getByRole('combobox', { name: 'Box' })).toHaveAccessibleDescription('Choose the box')
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Box' }), box.public_id)
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Row' }), '1')
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Column' }), '1')
    await user.click(within(dialog).getByRole('button', { name: 'Place vial' }))
    expect(await within(dialog).findByText('Another vial is in this position. Choose another one.')).toBeInTheDocument()
    expect(dialog).toHaveAccessibleDescription(/Another vial is in this position/)
  })

  it('changes a state along the allowed edges, with a reason', async () => {
    mockMaterial()
    const calls = mockApi('post', '/api/v1/labs/{lab_public_id}/vials/{public_id}/status/', { ...loose, status: 'quarantined' })
    await render()
    const user = userEvent.setup()
    await vialAction(user, 'MYC 42 / 1 / 2', 'Change state')
    const dialog = await screen.findByRole('dialog', { name: 'Change the state of vial MYC 42 / 1 / 2' })
    const state = within(dialog).getByRole('combobox', { name: 'New state' })
    expect(within(state).getAllByRole('option').map((o) => o.textContent)).toEqual(['Quarantined', 'To destroy', 'Consumed', 'Lost', 'Entered in error'])
    await user.click(within(dialog).getByRole('button', { name: 'Save state' }))
    expect(within(dialog).getByRole('textbox', { name: 'Reason' })).toHaveAccessibleDescription('Stored for good with the change. Name no person. Say why')
    expect(calls).toHaveLength(0)
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'contamination suspected')
    await user.click(within(dialog).getByRole('button', { name: 'Save state' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ status: 'quarantined', reason: 'contamination suspected' })
  })

  it('offers no "entered in error" for a vial whose state changed before', async () => {
    mockMaterial([makeVial({ label: 'MYC 42 / 2 / 1', status_changed_at: '2026-10-02T10:00:00Z' })])
    await render()
    const user = userEvent.setup()
    await vialAction(user, 'MYC 42 / 2 / 1', 'Change state')
    const state = within(await screen.findByRole('dialog')).getByRole('combobox', { name: 'New state' })
    expect(within(state).queryByRole('option', { name: 'Entered in error' })).not.toBeInTheDocument()
  })

  it('revives a vial after a confirmation that names the cost', async () => {
    mockMaterial()
    const calls = mockApi('post', '/api/v1/labs/{lab_public_id}/vials/{public_id}/revive/', makePassage({ number: 2, source_kind: 'vial' }))
    await render()
    const user = userEvent.setup()
    await vialAction(user, 'MYC 42 / 1 / 2', 'Revive')
    const dialog = await screen.findByRole('alertdialog', { name: 'Revive vial MYC 42 / 1 / 2?' })
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus()
    await user.click(within(dialog).getByRole('button', { name: 'Revive vial' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls).toHaveLength(1)
  })

  it('records a subculture of a passage', async () => {
    mockMaterial()
    const calls = mockApi('post', PASSAGES, makePassage({ number: 2, source_kind: 'passage' }))
    await render()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Subculture passage 1' }))
    const dialog = await screen.findByRole('dialog', { name: 'Subculture passage 1' })
    await user.click(within(dialog).getByRole('button', { name: 'Record subculture' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ source_passage: one.public_id })
  })
})

const answer = { location: { box: '00000000-0000-4000-8000-000000000b01', box_name: 'Box R', path: ['Freezer A', 'Rack 1', 'Box R'], row: 1, col: 2, label: 'A2' } }
/** Mutations that still hold an answer, a revealed location among them. */
const revealed = (client: QueryClient) =>
  client
    .getMutationCache()
    .getAll()
    .filter((m) => m.state.data !== undefined)

describe('the location of a regulated strain', { timeout: 20_000 }, () => {
  const masked = makeVial({ label: 'MYC 7 / 1 / 1', placed: true, location_masked: true })

  it('is hidden without a way to reveal it for a reader without the grant', async () => {
    mockMaterial([masked])
    const reveals = recordRequests('post', REVEAL)
    await render()
    const vials = await screen.findByRole('table', { name: 'Vials' })
    const row = within(vials).getAllByRole('row')[1]
    expect(row && within(row).getAllByRole('cell')[2]).toHaveTextContent('Hidden: regulated strain')
    expect(screen.queryByRole('button', { name: /Reveal/ })).not.toBeInTheDocument()
    expect(reveals).toHaveLength(0)
  })

  it('is revealed on request for a holder, each time anew, and hidden again', async () => {
    mockMaterial([{ ...masked, can_reveal: true }])
    const held = holdApi('post', REVEAL)
    await render(false) // a viewer may hold the grant too
    const user = userEvent.setup()
    const button = await screen.findByRole('button', { name: 'Reveal the location of vial MYC 7 / 1 / 1' })
    await user.click(button)
    expect(button).toHaveAttribute('aria-disabled', 'true')
    await user.click(button) // pending: no second request
    expect(held.calls).toHaveLength(1)
    held.release(200, { location: { box: '00000000-0000-4000-8000-000000000b01', box_name: 'Box R', path: ['Freezer A', 'Rack 1', 'Box R'], row: 1, col: 2, label: 'A2' } })
    const text = await screen.findByText('Freezer A / Rack 1 / Box R, A2')
    expect(text).toHaveAttribute('aria-live', 'polite')
    expect(button).toHaveFocus()
    expect(button).toHaveAccessibleName('Hide the location of vial MYC 7 / 1 / 1')
    await user.click(button)
    expect(screen.queryByText(/Box R/)).not.toBeInTheDocument()
    expect(screen.getByText('Hidden: regulated strain')).toBeInTheDocument()
    await user.click(button)
    await screen.findByText('Freezer A / Rack 1 / Box R, A2')
    expect(held.calls).toHaveLength(2) // never from a cache
  })

  it('forgets a revealed location once the vial moved, and asks anew', async () => {
    const vial = { ...masked, can_reveal: true }
    mockMaterial([vial])
    const reveals = mockApi('post', REVEAL, answer, { status: 200 })
    mockApi('post', '/api/v1/labs/{lab_public_id}/vials/{public_id}/place/', vial, { status: 200 })
    await render()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Reveal the location of vial MYC 7 / 1 / 1' }))
    await screen.findByText('Freezer A / Rack 1 / Box R, A2')
    await vialAction(user, 'MYC 7 / 1 / 1', 'Move')
    const dialog = await screen.findByRole('dialog', { name: 'Move vial MYC 7 / 1 / 1' })
    await user.selectOptions(await within(dialog).findByRole('combobox', { name: 'Box' }), box.public_id)
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Row' }), '1')
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Column' }), '1')
    await user.click(within(dialog).getByRole('button', { name: 'Move vial' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    // The old answer is gone: the vial is hidden again and only a new reveal says where it is.
    const vials = screen.getByRole('table', { name: 'Vials' })
    expect(vials).not.toHaveTextContent('Box R')
    expect(within(vials).getByText('Hidden: regulated strain')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reveal the location of vial MYC 7 / 1 / 1' })).toBeInTheDocument()
    expect(reveals).toHaveLength(1)
  })

  it('keeps a revealed location while another vial moves', async () => {
    const vial = { ...masked, can_reveal: true }
    const other = makeVial({ label: 'MYC 7 / 1 / 2' })
    mockMaterial([vial, other])
    mockApi('post', REVEAL, answer, { status: 200 })
    mockApi('post', '/api/v1/labs/{lab_public_id}/vials/{public_id}/place/', other, { status: 200 })
    await render()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Reveal the location of vial MYC 7 / 1 / 1' }))
    await screen.findByText('Freezer A / Rack 1 / Box R, A2')
    await vialAction(user, 'MYC 7 / 1 / 2', 'Place')
    const dialog = await screen.findByRole('dialog', { name: 'Place vial MYC 7 / 1 / 2' })
    await user.selectOptions(await within(dialog).findByRole('combobox', { name: 'Box' }), box.public_id)
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Row' }), '1')
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Column' }), '1')
    await user.click(within(dialog).getByRole('button', { name: 'Place vial' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(screen.getByText('Freezer A / Rack 1 / Box R, A2')).toBeInTheDocument()
  })

  it('forgets a revealed location after a state change from elsewhere, and keeps the focus on the page', async () => {
    const vial = { ...masked, can_reveal: true }
    mockMaterial([vial])
    mockApi('post', REVEAL, answer, { status: 200 })
    const { client } = await render()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Reveal the location of vial MYC 7 / 1 / 1' }))
    await screen.findByText('Freezer A / Rack 1 / Box R, A2')
    mockApi('get', VIALS, page([{ ...vial, status: 'quarantined', status_changed_at: '2026-10-20T10:00:00Z' }]))
    await client.refetchQueries({ queryKey: vialKeys.vials(LAB_ID, STRAIN_ID) })
    await waitFor(() => expect(screen.queryByText(/Box R/)).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Reveal the location of vial MYC 7 / 1 / 1' })).toBeInTheDocument()
    // The focused Hide button went with the old answer: focus goes to the section, not the body.
    await waitFor(() => expect(screen.getByRole('heading', { level: 2, name: 'Vials' })).toHaveFocus())
  })

  it('keeps no revealed location in the mutation cache after Hide or once the vial is gone', async () => {
    const vial = { ...masked, can_reveal: true }
    mockMaterial([vial])
    mockApi('post', REVEAL, answer, { status: 200 })
    const { client, unmount } = await render()
    const user = userEvent.setup()
    const button = await screen.findByRole('button', { name: 'Reveal the location of vial MYC 7 / 1 / 1' })
    await user.click(button)
    await screen.findByText('Freezer A / Rack 1 / Box R, A2')
    expect(revealed(client)).toHaveLength(1)
    await user.click(button) // Hide
    expect(revealed(client)).toHaveLength(0)
    await user.click(button)
    await screen.findByText('Freezer A / Rack 1 / Box R, A2')
    unmount()
    await waitFor(() => expect(client.getMutationCache().getAll()).toHaveLength(0))
  })

  it('says why when the grant was revoked meanwhile', async () => {
    mockMaterial([{ ...masked, can_reveal: true }])
    mockApiError('post', REVEAL, 403, problem(403, { code: 'location_grant_required' }))
    await render()
    await userEvent.setup().click(await screen.findByRole('button', { name: /Reveal the location/ }))
    expect(await screen.findByText("Only people the lab's managers named may see where regulated strains are.")).toBeInTheDocument()
  })
})

describe('moving a vial of a regulated strain', { timeout: 20_000 }, () => {
  it('shows nothing of where it is now: no box, row or column chosen, no position in the text', async () => {
    const masked = makeVial({ label: 'MYC 7 / 1 / 1', placed: true, location_masked: true })
    mockMaterial([masked])
    const calls = mockApi('post', '/api/v1/labs/{lab_public_id}/vials/{public_id}/place/', masked)
    await render()
    const user = userEvent.setup()
    await vialAction(user, 'MYC 7 / 1 / 1', 'Move')
    const dialog = await screen.findByRole('dialog', { name: 'Move vial MYC 7 / 1 / 1' })
    const boxField = await within(dialog).findByRole('combobox', { name: 'Box' })
    expect(boxField).toHaveValue('')
    expect(within(dialog).getByRole('combobox', { name: 'Row' })).toHaveValue('')
    expect(within(dialog).getByRole('combobox', { name: 'Column' })).toHaveValue('')
    // The box select lists every box; nothing else in the dialog names one or a position.
    expect(dialog).not.toHaveAccessibleDescription(/\b[A-I]\d\b|Box|from/)
    expect(within(dialog).getByRole('heading').textContent).toBe('Move vial MYC 7 / 1 / 1')
    await user.selectOptions(boxField, box.public_id)
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Row' }), '1')
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Column' }), '1')
    await user.click(within(dialog).getByRole('button', { name: 'Move vial' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ box: box.public_id, row: 1, col: 1 })
    // The answer is masked too: the row still says hidden, not where the vial went.
    const vials = screen.getByRole('table', { name: 'Vials' })
    expect(vials).toHaveTextContent('Hidden: regulated strain')
    expect(vials).not.toHaveTextContent(/Box 1|A1/)
  })
})
