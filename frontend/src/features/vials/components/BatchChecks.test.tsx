import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeBatch, makeCheck, makePassage, makeVial, page, problem, validationProblem } from '@/test/factories'
import { holdApi, mockApi, mockApiError, recordRequests } from '@/test/mockApi'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/render'
import type { Batch } from '../schemas'
import { StrainMaterial } from './StrainMaterial'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const STRAIN_ID = '00000000-0000-4000-8000-0000000000d1'
const BATCHES = '/api/v1/labs/{lab_public_id}/batches/'
const CHECKS = '/api/v1/labs/{lab_public_id}/batch-checks/'
const ERROR = '/api/v1/labs/{lab_public_id}/batch-checks/{public_id}/enter-in-error/'
const RELEASE = '/api/v1/labs/{lab_public_id}/batches/{public_id}/release/'
const HOLD = '/api/v1/labs/{lab_public_id}/batches/{public_id}/hold/'

const pending = makeBatch({ number: 1, latest_checks: { identity: 'pass', purity: null, viability: 'reduced' } })
const ready = makeBatch({ number: 2, purpose: 'distribution', latest_checks: { identity: 'pass', purity: 'pass', viability: 'reduced' } })
const released = makeBatch({
  number: 3,
  status: 'released',
  status_reason: 'All three passed.',
  status_changed_at: '2026-10-03T10:00:00Z',
  latest_checks: { identity: 'pass', purity: 'pass', viability: 'pass' },
  vials_available: 4,
  vials_distributable: 4,
})
const held = makeBatch({
  number: 4,
  status: 'on_hold',
  status_reason: 'The purity check of 2026-10-02 failed.',
  status_changed_at: '2026-10-02T10:00:00Z',
  latest_checks: { identity: 'pass', purity: 'fail', viability: 'pass' },
})
const vialOne = makeVial({ label: 'MYC 42 / 1 / 1', batch: pending.public_id })
const vialTwo = makeVial({ label: 'MYC 42 / 1 / 2', batch: pending.public_id, status: 'quarantined', status_changed_at: '2026-10-02T10:00:00Z' })
const usedVial = makeVial({ label: 'MYC 42 / 1 / 3', batch: pending.public_id, status: 'consumed', status_changed_at: '2026-10-03T10:00:00Z' })
const otherBatchVial = makeVial({ label: 'MYC 42 / 2 / 1', batch: ready.public_id })
const viability = makeCheck({
  batch: pending.public_id,
  result: 'reduced',
  method: 'plate_count',
  method_detail: 'TSA, 30 °C',
  value: '15000000.0000',
  unit: 'cfu_per_ml',
  vial: usedVial.public_id,
  vial_label: 'MYC 42 / 1 / 3',
  note: 'A tenth of the count at preservation.',
  checked_on: '2026-10-03',
})
const wrong = makeCheck({ batch: pending.public_id, kind: 'purity', method: 'streak_plate', result: 'fail', status: 'entered_in_error', reason: 'recorded on the wrong batch' })
const identity = makeCheck({ batch: pending.public_id, kind: 'identity', method: 'sequencing', performed_by: 'tech-two' })

function mockMaterial(batches: Batch[] = [pending, ready, released, held]) {
  mockApi('get', '/api/v1/labs/{lab_public_id}/passages/', page([makePassage({ number: 0 })]))
  mockApi('get', BATCHES, page(batches))
  mockApi('get', '/api/v1/labs/{lab_public_id}/vials/', page([vialOne, vialTwo, usedVial, otherBatchVial]))
  mockApi('get', '/api/v1/labs/{lab_public_id}/storage-units/', [])
  mockApi('get', CHECKS, page([viability, wrong, identity]))
}

const FIRST_PAGE = { limit: 50, offset: 0, batch: undefined }
const render = ({ canHandle = true, canRelease = false } = {}) =>
  renderWithProviders(<StrainMaterial labId={LAB_ID} strainId={STRAIN_ID} accession="MYC 42" canHandle={canHandle} canRelease={canRelease} vialPage={FIRST_PAGE} onVialPage={() => undefined} />)

async function openChecks(number: number) {
  const user = userEvent.setup()
  const toggle = await screen.findByRole('button', { name: `Checks of batch ${number}` })
  await user.click(toggle)
  return { user, toggle }
}

describe('the checks of a batch', { timeout: 20_000 }, () => {
  it('shows each status with why it is not released, and how many vials may go out', async () => {
    mockMaterial()
    await render({ canHandle: false })
    const table = await screen.findByRole('table', { name: 'Batches' })
    const status = (row: number) => within(within(table).getAllByRole('row')[row] ?? table).getAllByRole('cell')[5]?.textContent
    expect(status(1)).toBe('Pending checkWaiting for a passed purity check.')
    expect(status(2)).toBe('Pending checkAll checks passed. A curator releases it.')
    expect(status(3)).toBe('Released')
    expect(status(4)).toBe('On holdThe purity check of 2026-10-02 failed.')
    expect(screen.getByText('Available for distribution: 4 vials, from released batch 3.')).toBeInTheDocument()
  })

  it('says when no vial may go out', async () => {
    mockMaterial([pending, held])
    await render({ canHandle: false })
    expect(await screen.findByText('Available for distribution: none. No released batch of distribution stock has a vial left.')).toBeInTheDocument()
  })

  it('opens a batch as a disclosure, loads its history only then, and shows a viewer no actions', async () => {
    mockMaterial()
    const loads = recordRequests('get', CHECKS)
    await render({ canHandle: false })
    await screen.findByRole('table', { name: 'Batches' })
    expect(loads).toHaveLength(0)
    const { user, toggle } = await openChecks(1)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    const panel = document.getElementById(toggle.getAttribute('aria-controls') ?? '')
    expect(panel).not.toBeNull()
    expect(within(panel ?? document.body).getByRole('heading', { level: 3 })).toHaveTextContent('Batch 1: Pending check')
    const latest = within(panel ?? document.body).getByRole('list', { name: 'Latest checks of batch 1' })
    expect(within(latest).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['Identity: Passed', 'Purity: not checked yet', 'Viability: Reduced'])
    const history = await screen.findByRole('list', { name: 'Checks of batch 1' })
    expect(loads[0]?.url.searchParams.get('batch')).toBe(pending.public_id)
    const items = within(history).getAllByRole('listitem')
    expect(items[0]).toHaveTextContent(
      '2026-10-03, Viability, ReducedPlate count (TSA, 30 °C), 15000000 CFU/mL, vial MYC 42 / 1 / 3, after preservation, by technicianA tenth of the count at preservation.',
    )
    expect(items[1]).toHaveTextContent('2026-10-02, Purity, Failed, entered in error')
    expect(items[1]).toHaveTextContent('Why it was entered in error: recorded on the wrong batch')
    expect(items[2]).toHaveTextContent('by tech-two')
    expect(screen.queryByRole('button', { name: /Record a check|Release|Hold|in error/ })).not.toBeInTheDocument()
    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('list', { name: 'Checks of batch 1' })).not.toBeInTheDocument()
  })

  it('says when a batch has no check yet', async () => {
    mockMaterial()
    mockApi('get', CHECKS, page([]))
    await render()
    await openChecks(1)
    expect(await screen.findByText('No check recorded yet.')).toBeInTheDocument()
  })

  it('shows a failed history load with a retry', async () => {
    allowConsole(/API error 500/)
    mockMaterial()
    mockApiError('get', CHECKS, 500)
    await render()
    await openChecks(1)
    expect(await screen.findByText(/Could not load the checks/)).toBeInTheDocument()
    mockApi('get', CHECKS, page([]))
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('No check recorded yet.')).toBeInTheDocument()
  })

  it('records a check by keyboard: the methods follow the kind, the vial is one of the batch, the lists refresh', async () => {
    mockMaterial()
    const calls = mockApi('post', CHECKS, makeCheck({ kind: 'purity' }))
    const reloads = recordRequests('get', BATCHES)
    // The page of the table holds none of the batch's vials; the batch's own read does.
    server.use(
      http.get('*/api/v1/labs/:lab/vials/', ({ request }) =>
        HttpResponse.json(new URL(request.url).searchParams.get('batch') === pending.public_id ? page([vialOne, vialTwo, usedVial]) : page([otherBatchVial])),
      ),
    )
    const vialReads = recordRequests('get', '/api/v1/labs/{lab_public_id}/vials/')
    await render()
    const { user } = await openChecks(1)
    const trigger = await screen.findByRole('button', { name: 'Record a check' })
    trigger.focus()
    await user.keyboard('{Enter}')
    const dialog = await screen.findByRole('dialog', { name: 'Record a check of batch 1' })
    expect(dialog).toHaveAccessibleDescription(/It waits for a passed purity check\./)
    // The batch's own vials, all of them, asked for with the dialog (#72), not the page on screen.
    await within(dialog).findByRole('combobox', { name: 'Vial checked' })
    expect(vialReads.map((r) => r.url.searchParams.get('batch'))).toContain(pending.public_id)
    const kind = within(dialog).getByRole('combobox', { name: 'Kind' })
    await waitFor(() => expect(kind).toHaveFocus())
    expect(kind).toHaveValue('purity') // the kind it waits for
    expect(within(dialog).getByRole('combobox', { name: 'Stage' })).toHaveValue('periodic') // it has checks
    const method = () => within(dialog).getByRole('combobox', { name: 'Method' })
    expect(within(method()).getAllByRole('option').map((o) => o.textContent)).toEqual(['Streak plate', 'Microscopy', 'Other'])
    await user.selectOptions(kind, 'viability')
    expect(within(method()).getAllByRole('option').map((o) => o.textContent)).toEqual(['Growth after revival', 'Plate count', 'Live and dead staining', 'Other'])
    expect(method()).toHaveValue('growth')
    await user.selectOptions(method(), 'plate_count')
    await user.type(within(dialog).getByRole('textbox', { name: 'Value' }), '2.1e8')
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Unit' }), 'cfu_per_ml')
    const vial = within(dialog).getByRole('combobox', { name: 'Vial checked' })
    // Available vials of this batch, and the one an earlier check of it used; no other batch's.
    expect(within(vial).getAllByRole('option').map((o) => o.textContent)).toEqual(['None named', 'MYC 42 / 1 / 1', 'MYC 42 / 1 / 3, used by an earlier check'])
    await user.selectOptions(vial, vialOne.public_id)
    await user.type(within(dialog).getByRole('textbox', { name: 'Note' }), ' grew well ')
    await user.click(within(dialog).getByRole('button', { name: 'Record check' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({
      batch: pending.public_id,
      kind: 'viability',
      stage: 'periodic',
      checked_on: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      method: 'plate_count',
      method_detail: '',
      result: 'pass',
      value: '2.1e8',
      unit: 'cfu_per_ml',
      vial: vialOne.public_id,
      note: 'grew well',
      reason: '',
    })
    expect(calls[0]?.headers.get('X-CSRFToken')).toBeTruthy()
    expect(reloads.length).toBeGreaterThan(0)
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it.each([
    ['a reduced result without a note', { result: 'reduced' }, 'Note', 'Say what was reduced'],
    ['another method undescribed', { method: 'other' }, 'Method details', 'Describe the method'],
    ['a value without a unit', { value: '12' }, 'Unit', 'Choose the unit of the value'],
    ['a unit without a value', { unit: 'percent' }, 'Value', 'Enter the value, or no unit'],
    ['a percentage above 100', { value: '101', unit: 'percent' }, 'Value', 'A percentage is at most 100'],
    ['a value that is no number', { value: 'many', unit: 'percent' }, 'Value', 'Enter a number, as 12.5 or 2.1e8'],
    ['a date in the future', { checked_on: '2999-01-01' }, 'Checked on', 'This date is in the future'],
  ] as const)('sends nothing for %s and says so on the field', async (_, values, field, message) => {
    mockMaterial()
    const calls = recordRequests('post', CHECKS)
    await render()
    const { user } = await openChecks(1)
    await user.click(await screen.findByRole('button', { name: 'Record a check' }))
    const dialog = await screen.findByRole('dialog', { name: 'Record a check of batch 1' })
    for (const [name, value] of Object.entries(values)) {
      const label = { result: 'Result', method: 'Method', unit: 'Unit', value: 'Value', checked_on: 'Checked on' }[name] ?? name
      const control = within(dialog).getByLabelText(label, { selector: 'input, select, textarea' })
      if (control instanceof HTMLSelectElement) await user.selectOptions(control, value)
      else {
        await user.clear(control)
        await user.type(control, value)
      }
    }
    await user.click(within(dialog).getByRole('button', { name: 'Record check' }))
    const target = within(dialog).getByLabelText(field, { selector: 'input, select, textarea' })
    expect(target).toHaveAccessibleDescription(expect.stringContaining(message))
    expect(target).toHaveFocus()
    expect(calls).toHaveLength(0)
  })

  it('puts a server field error on its field and a conflict in the dialog', async () => {
    mockMaterial()
    mockApiError('post', CHECKS, 400, validationProblem([{ attr: 'checked_on', code: 'invalid', detail: 'The batch was preserved on 2026-10-01: a check is not dated before.' }]))
    await render()
    const { user } = await openChecks(1)
    await user.click(await screen.findByRole('button', { name: 'Record a check' }))
    const dialog = await screen.findByRole('dialog', { name: 'Record a check of batch 1' })
    await user.click(within(dialog).getByRole('button', { name: 'Record check' }))
    const date = within(dialog).getByRole('textbox', { name: 'Checked on' })
    await waitFor(() => expect(date).toHaveAccessibleDescription(/a check is not dated before\.$/))
    expect(date).toHaveFocus()
    mockApiError('post', CHECKS, 409, problem(409, { code: 'vial_not_available' }))
    await user.click(within(dialog).getByRole('button', { name: 'Record check' }))
    expect(await within(dialog).findByText('This vial is not available any more. Choose another one, or none.')).toBeInTheDocument()
  })

  it('keeps the record dialog open and its confirm focusable while the request runs', async () => {
    mockMaterial()
    const request = holdApi('post', CHECKS)
    await render()
    const { user } = await openChecks(1)
    await user.click(await screen.findByRole('button', { name: 'Record a check' }))
    const dialog = await screen.findByRole('dialog', { name: 'Record a check of batch 1' })
    const confirm = within(dialog).getByRole('button', { name: 'Record check' })
    await user.click(confirm)
    await waitFor(() => expect(confirm).toHaveAttribute('aria-busy', 'true'))
    await user.click(confirm)
    await user.keyboard('{Escape}')
    expect(request.calls).toHaveLength(1)
    expect(dialog).toBeInTheDocument()
    request.release(201, makeCheck())
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
  })

  it('lets a curator release a batch whose checks passed, with a reason, and moves the focus to the batch heading', async () => {
    mockMaterial()
    const calls = mockApi('post', RELEASE, { ...ready, status: 'released' }, { status: 200 })
    await render({ canRelease: true })
    const { user } = await openChecks(2)
    expect(screen.queryByRole('button', { name: 'Record a check' })).toBeInTheDocument()
    const release = await screen.findByRole('button', { name: 'Release' })
    expect(screen.getByRole('button', { name: 'Hold' })).toBeInTheDocument()
    await user.click(release)
    const dialog = await screen.findByRole('dialog', { name: 'Release batch 2' })
    const reason = within(dialog).getByRole('textbox', { name: 'Reason' })
    await waitFor(() => expect(reason).toHaveFocus())
    await user.click(within(dialog).getByRole('button', { name: 'Release batch' }))
    expect(reason).toHaveAccessibleDescription(/Say why$/)
    expect(calls).toHaveLength(0)
    await user.type(reason, ' all three passed ')
    // The refreshed batch is released: Release is gone, so the focus goes to the batch's heading.
    mockApi('get', BATCHES, page([pending, { ...ready, status: 'released', status_reason: 'all three passed', vials_distributable: 3 }, released, held]))
    await user.click(within(dialog).getByRole('button', { name: 'Release batch' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ reason: 'all three passed' })
    await waitFor(() => expect(screen.getByRole('heading', { level: 3, name: 'Batch 2: Released' })).toHaveFocus())
    expect(screen.queryByRole('button', { name: 'Release' })).not.toBeInTheDocument()
    expect(screen.getByText('Available for distribution: 7 vials, from released batches 2, 3.')).toBeInTheDocument()
  })

  it('offers no release while a kind has not passed, and holds with a reason', async () => {
    mockMaterial()
    const calls = mockApi('post', HOLD, { ...pending, status: 'on_hold' }, { status: 200 })
    await render({ canRelease: true })
    const { user } = await openChecks(1)
    await screen.findByRole('list', { name: 'Checks of batch 1' })
    expect(screen.queryByRole('button', { name: 'Release' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Hold' }))
    const dialog = await screen.findByRole('dialog', { name: 'Hold batch 1' })
    expect(dialog).toHaveAccessibleDescription('Nothing of a held batch is sent until a curator releases it again.')
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'a recipient reported a mixed culture')
    await user.click(within(dialog).getByRole('button', { name: 'Hold batch' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ reason: 'a recipient reported a mixed culture' })
  })

  it('says inside the dialog when the release rule refuses', async () => {
    mockMaterial()
    mockApiError('post', RELEASE, 422, problem(422, { code: 'checks_not_passed' }))
    await render({ canRelease: true })
    const { user } = await openChecks(2)
    await user.click(await screen.findByRole('button', { name: 'Release' }))
    const dialog = await screen.findByRole('dialog', { name: 'Release batch 2' })
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'passed')
    await user.click(within(dialog).getByRole('button', { name: 'Release batch' }))
    expect(
      await within(dialog).findByText('A batch is released once its latest identity, purity and viability checks passed. Reload to see its checks.'),
    ).toBeInTheDocument()
  })

  it('offers a technician no release or hold, also on a batch whose checks passed', async () => {
    mockMaterial()
    await render({ canHandle: true, canRelease: false })
    await openChecks(2)
    await screen.findByRole('list', { name: 'Checks of batch 2' })
    expect(screen.getByRole('button', { name: 'Record a check' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^(Release|Hold)$/ })).not.toBeInTheDocument()
  })

  it('offers a held batch with a failed kind neither release nor hold, a released one only hold', async () => {
    mockMaterial()
    await render({ canRelease: true })
    const { user } = await openChecks(4)
    await screen.findByRole('list', { name: 'Checks of batch 4' })
    expect(screen.queryByRole('button', { name: /^(Release|Hold)$/ })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Checks of batch 4' }))
    await user.click(screen.getByRole('button', { name: 'Checks of batch 3' }))
    await screen.findByRole('list', { name: 'Checks of batch 3' })
    expect(screen.queryByRole('button', { name: 'Release' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Hold' })).toBeInTheDocument()
  })

  it('enters a wrong check in error after an alert that names the cost, with a reason', async () => {
    mockMaterial()
    const calls = mockApi('post', ERROR, { ...identity, status: 'entered_in_error', reason: 'typo' }, { status: 200 })
    await render()
    const { user } = await openChecks(1)
    await screen.findByRole('list', { name: 'Checks of batch 1' })
    expect(screen.getAllByRole('button', { name: /in error$/ })).toHaveLength(2) // not the one already in error
    const trigger = screen.getByRole('button', { name: `Enter the identity check of ${identity.checked_on} in error` })
    await user.click(trigger)
    const dialog = await screen.findByRole('alertdialog', { name: `Enter the identity check of ${identity.checked_on} in error?` })
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus()
    await user.click(within(dialog).getByRole('button', { name: 'Enter in error' }))
    expect(within(dialog).getByRole('textbox', { name: 'Reason' })).toHaveAccessibleDescription(/Say why$/)
    expect(calls).toHaveLength(0)
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'typo')
    await user.click(within(dialog).getByRole('button', { name: 'Enter in error' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ reason: 'typo' })
    await waitFor(() => expect(trigger).toHaveFocus())
  })
})
