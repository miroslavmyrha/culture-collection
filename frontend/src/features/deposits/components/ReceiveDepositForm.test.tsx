import { screen, waitFor, within } from '@testing-library/react'
import userEvent, { type UserEvent } from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeDeposit, makeDepositor, makeMtaTemplate, page, problem, validationProblem } from '@/test/factories'
import { holdApi, mockApi, mockApiError, recordRequests } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { type Deposit, USES } from '../schemas'
import { ReceiveDepositForm } from './ReceiveDepositForm'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const PATH = '/api/v1/labs/{lab_public_id}/deposits/'
// Invented people at example.org, invented taxa elsewhere: test data states no real facts.
const jana = makeDepositor({ name: 'Jana Vzorová', institution: 'Example University' })
const std = makeMtaTemplate({ code: 'STD', version: 2, title: 'Standard MTA' })

async function setup() {
  mockApi('get', '/api/v1/labs/{lab_public_id}/depositors/', page([jana]))
  mockApi('get', '/api/v1/labs/{lab_public_id}/mta-templates/', page([std]))
  const onReceived = vi.fn<(deposit: Deposit) => void>()
  const view = await renderWithProviders(<ReceiveDepositForm labId={LAB_ID} onReceived={onReceived} />)
  return { ...view, onReceived, user: userEvent.setup() }
}

const field = (name: string) => screen.getByRole('textbox', { name })
const select = (name: string) => screen.getByRole('combobox', { name })
const uses = () => within(screen.getByRole('group', { name: 'Uses' })).getAllByRole('combobox')

async function pickDepositor(user: UserEvent) {
  await user.click(select('Depositor'))
  await user.keyboard('vzor')
  await screen.findByRole('option', { name: /Jana Vzorová/ }, { timeout: 10_000 })
  await user.keyboard('{ArrowDown}{Enter}')
}

async function fillRequired(user: UserEvent, decision = 'permit') {
  await pickDepositor(user)
  await user.type(field('Name as received'), 'Testella exempli K3')
  for (const use of uses()) await user.selectOptions(use, decision)
  await user.selectOptions(select('ABS scope'), 'not_in_scope')
}

const submit = (user: UserEvent) => user.click(screen.getByRole('button', { name: 'Record the deposit' }))

describe('ReceiveDepositForm', { timeout: 25_000 }, () => {
  it('sends the receipt with every use decided, the MTA and the ABS facts, with the CSRF token', async () => {
    const received = makeDeposit()
    const calls = mockApi('post', PATH, received)
    const { user, onReceived } = await setup()
    await fillRequired(user)
    await user.selectOptions(select('Redistribution to third parties'), 'deny')
    await user.selectOptions(select('Condition on arrival'), 'damaged')
    await user.type(field('Note on the condition'), 'cracked ampoule')
    await user.type(field('Passages stated by the depositor'), '3')
    await user.selectOptions(select('MTA'), std.public_id)
    await user.selectOptions(select('ABS scope'), 'in_scope')
    await user.type(field('Permit reference'), 'Permit DEV/1')
    await user.click(screen.getByRole('checkbox', { name: 'Teaching' }))
    await user.click(screen.getByRole('checkbox', { name: 'Non-commercial research' }))
    await user.selectOptions(select('Country of origin'), 'CZ')
    await user.type(field('Collection date'), '2019-05')
    await submit(user)
    await waitFor(() => expect(onReceived).toHaveBeenCalledWith(received), { timeout: 5000 })
    expect(calls[0]?.headers.get('X-CSRFToken')).toBe('test-token')
    expect(calls[0]?.body).toEqual({
      depositor: jana.public_id,
      received_on: new Date().toLocaleDateString('sv'),
      condition: 'damaged',
      condition_note: 'cracked ampoule',
      name_as_received: 'Testella exempli K3',
      depositor_passages: 3,
      terms: {
        mta: std.public_id,
        abs_scope: 'in_scope',
        country_of_origin: 'CZ',
        collection_date: '2019-05',
        pic_reference: '',
        mat_reference: '',
        ircc: '',
        permit_reference: 'Permit DEV/1',
        uses: USES.map((use) => ({ use, decision: use === 'redistribution' ? 'deny' : 'permit' })),
        mat_uses: ['research_noncommercial', 'teaching'],
      },
    })
  })

  it('does not send the last valid passage count or date while the field shows an invalid one (#111)', async () => {
    const calls = mockApi('post', PATH, makeDeposit())
    const { user } = await setup()
    await fillRequired(user)
    const today = new Date().toLocaleDateString('sv')
    const cases: readonly (readonly [string, string, readonly string[], string])[] = [
      ['Passages stated by the depositor', '3', ['3x', '-1', '1,5', '123456'], 'Enter a whole number, or leave it empty'],
      ['Received on', today, ['2026-13-45', '12.10.2026', '2026-10'], 'Enter a date as YYYY-MM-DD'],
      ['Collection date', '2019-05', ['2019-5', '19-05-01', '2019-05-01x'], 'Use YYYY, YYYY-MM or YYYY-MM-DD'],
    ]
    for (const [label, valid, invalid, message] of cases) {
      const input = field(label)
      await user.clear(input)
      await user.type(input, valid)
      for (const typed of invalid) {
        await user.clear(input)
        await user.type(input, typed)
        await submit(user)
        await waitFor(() => expect(input).toHaveAccessibleDescription(expect.stringContaining(message)))
        expect(input).toHaveValue(typed)
        expect(calls).toHaveLength(0)
      }
      await user.clear(input)
      await user.type(input, valid)
    }
  })

  it('presets no use and no scope: each must be chosen, the depositor focused first, nothing sent', async () => {
    const calls = recordRequests('post', PATH)
    const { user } = await setup()
    expect(uses()).toHaveLength(USES.length)
    for (const use of uses()) expect(use).toHaveValue('')
    await submit(user)
    expect(select('Depositor')).toHaveFocus()
    expect(select('Depositor')).toHaveAccessibleDescription(/Choose the depositor$/)
    expect(uses()[0]).toHaveAccessibleDescription('Choose a decision')
    expect(select('ABS scope')).toHaveAccessibleDescription(/Choose the scope$/)
    expect(calls).toHaveLength(0)
  })

  it('asks for a note when the material did not arrive intact, and for an IRCC or permit when in scope', async () => {
    const calls = recordRequests('post', PATH)
    const { user } = await setup()
    await fillRequired(user)
    await user.selectOptions(select('Condition on arrival'), 'other')
    await user.selectOptions(select('ABS scope'), 'in_scope')
    await submit(user)
    await waitFor(() => expect(field('Note on the condition')).toHaveFocus(), { timeout: 5000 })
    expect(field('Note on the condition')).toHaveAccessibleDescription(/Say what was wrong with it$/)
    expect(field('IRCC')).toHaveAccessibleDescription(/Material in scope needs an IRCC or a permit reference$/)
    expect(calls).toHaveLength(0)
  })

  it.each([
    ['terms.ircc', () => field('IRCC')],
    ['terms.uses.3.decision', () => uses()[3]],
    ['name_as_received', () => field('Name as received')],
    ['depositor', () => select('Depositor')],
  ])('puts a server error on %s and focuses it', async (attr, input) => {
    mockApiError('post', PATH, 400, validationProblem([{ attr, code: 'invalid', detail: 'Not like this.' }]))
    const { user } = await setup()
    await fillRequired(user)
    await submit(user)
    await waitFor(() => expect(input()).toHaveAccessibleDescription(/Not like this\.$/), { timeout: 5000 })
    expect(input()).toHaveFocus()
  })

  it('shows one safe message for a 403', async () => {
    allowConsole(/API error/)
    mockApiError('post', PATH, 403, problem(403, { detail: 'internal detail' }))
    const { user } = await setup()
    await fillRequired(user)
    await submit(user)
    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have permission to do that.')
    expect(screen.queryByText('internal detail')).not.toBeInTheDocument()
  })

  it('offers no depositor whose contact was erased', async () => {
    mockApi('get', '/api/v1/labs/{lab_public_id}/depositors/', page([jana, makeDepositor({ name: '', institution: 'Vzor Institute', erased: true })]))
    mockApi('get', '/api/v1/labs/{lab_public_id}/mta-templates/', page([std]))
    await renderWithProviders(<ReceiveDepositForm labId={LAB_ID} onReceived={vi.fn<(deposit: Deposit) => void>()} />)
    const user = userEvent.setup()
    await user.click(select('Depositor'))
    await user.keyboard('vzor')
    const listbox = await screen.findByRole('listbox', undefined, { timeout: 10_000 })
    expect(within(listbox).getAllByRole('option').map((o) => o.textContent)).toEqual(['Jana Vzorová, Example University'])
  })

  it('adds a new depositor in a dialog and chooses them, focus back on the button', async () => {
    const petr = makeDepositor({ name: 'Petr Příklad', institution: '' })
    mockApi('post', '/api/v1/labs/{lab_public_id}/depositors/', petr)
    const { user } = await setup()
    const add = screen.getByRole('button', { name: 'Add a depositor' })
    await user.click(add)
    const dialog = await screen.findByRole('dialog', { name: 'Add a depositor' })
    await user.type(within(dialog).getByRole('textbox', { name: 'Name' }), 'Petr Příklad')
    await user.click(within(dialog).getByRole('button', { name: 'Add the depositor' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument(), { timeout: 5000 })
    expect(select('Depositor')).toHaveValue('Petr Příklad')
    await waitFor(() => expect(add).toHaveFocus(), { timeout: 5000 })
  })

  it('keeps the focus on Record the deposit while it sends, and sends once', async () => {
    const held = holdApi('post', PATH)
    const { user } = await setup()
    await fillRequired(user)
    const button = screen.getByRole('button', { name: 'Record the deposit' })
    await user.click(button)
    await waitFor(() => expect(button).toHaveAttribute('aria-disabled', 'true'), { timeout: 5000 })
    expect(button).toHaveFocus()
    await user.click(button)
    expect(held.calls).toHaveLength(1)
    // No MTA chosen: the API gets null, never an empty id.
    expect(held.calls[0]?.body).toMatchObject({ terms: { mta: null } })
    held.release(201, makeDeposit())
    await waitFor(() => expect(button).toHaveAttribute('aria-disabled', 'false'), { timeout: 5000 })
  })
})
