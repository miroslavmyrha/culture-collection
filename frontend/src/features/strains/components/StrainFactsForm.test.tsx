import { screen, waitFor, within } from '@testing-library/react'
import userEvent, { type UserEvent } from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { allowConsole } from '@/test/console'
import { useMutation } from '@tanstack/react-query'
import { api, ensureCsrf, unwrap } from '@/lib/api'
import { makeDeposit, makeTaxon, page, problem, validationProblem } from '@/test/factories'
import { holdApi, mockApi, mockApiError, recordRequests } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { type StrainFactsBody, StrainFactsForm } from './StrainFactsForm'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const DEPOSIT_ID = '00000000-0000-4000-8000-0000000000d1'
// The page passes the deposit's accept mutation; this one sends the same request.
const PATH = '/api/v1/labs/{lab_public_id}/deposits/{public_id}/accept/'
// Invented taxa: the tests pair them with restrictions and risk groups, which no real
// organism should be shown with unless the facts hold.
const exempli = makeTaxon({ public_id: '00000000-0000-4000-8000-0000000000c1', name: 'Testella exempli', authority: 'Doe 2001' })
const fictivibrio = makeTaxon({ public_id: '00000000-0000-4000-8000-0000000000c2', name: 'Fictivibrio exempli', status: 'synonym' })

function Harness({ onDone, country }: { onDone: () => void; country?: 'CZ' }) {
  const accept = useMutation({
    mutationFn: async (body: StrainFactsBody) => {
      await ensureCsrf()
      return unwrap(api.POST(PATH, { params: { path: { lab_public_id: LAB_ID, public_id: DEPOSIT_ID } }, body }))
    },
    meta: { handlesError: true },
  })
  return (
    <StrainFactsForm label="Accept the deposit" submitLabel="Accept" nameAsReceived="T. exempli T1" submit={accept} onDone={onDone} country={country} />
  )
}

async function setup(country?: 'CZ') {
  mockApi('get', '/api/v1/taxa/', page([exempli, fictivibrio]))
  const onDone = vi.fn<() => void>()
  const view = await renderWithProviders(<Harness onDone={onDone} country={country} />)
  const user = userEvent.setup()
  return { ...view, user, onDone, form: screen.getByRole('form', { name: 'Accept the deposit' }) }
}

const field = (name: string) => screen.getByRole('textbox', { name })
const select = (name: string) => screen.getByRole('combobox', { name })

/** The taxon by keyboard: type, ArrowDown to the first match, Enter. */
async function pickTaxon(user: UserEvent, text = 'exem') {
  await user.click(select('Taxon'))
  await user.keyboard(text)
  await screen.findByRole('option', { name: /Testella exempli/ }, { timeout: 30_000 })
  await user.keyboard('{ArrowDown}{Enter}')
}

async function fillRequired(user: UserEvent) {
  await pickTaxon(user)
  await user.clear(field('Identified on'))
  await user.type(field('Identified on'), '2026-01-10')
  await user.type(field('Identification method'), '16S rRNA gene sequence')
  await user.selectOptions(select('Risk group'), '2')
}

const submit = (user: UserEvent) => user.click(screen.getByRole('button', { name: 'Accept' }))

// Long forms typed key by key, beside other test files: more than the default 5 s per test. The taxon
// search waits out its 250 ms debounce, and a busy machine needs a multiple of the quiet time (#60).
describe('StrainFactsForm', { timeout: 60_000 }, () => {
  it('sends the facts with their restrictions and the CSRF token, never a name', async () => {
    const calls = mockApi('post', PATH, makeDeposit({ status: 'accepted' }))
    const { user, onDone } = await setup()
    expect(screen.getByText('T. exempli T1')).toBeInTheDocument()
    await fillRequired(user)
    await user.selectOptions(select('Plant pathogenicity'), 'pathogenic')
    await user.type(field('Isolation source'), ' garden  soil ')
    await user.selectOptions(select('Country of origin'), 'CZ')
    await user.type(field('Isolation date'), '2019-05')
    await user.click(screen.getByRole('button', { name: 'Add a restriction' }))
    const first = screen.getByRole('group', { name: 'Restriction 1' })
    await user.selectOptions(within(first).getByRole('combobox', { name: 'Kind' }), 'dual_use')
    expect(within(first).getByRole('textbox', { name: 'List entry' })).toHaveAccessibleDescription(/1C351\.c/)
    await user.type(within(first).getByRole('textbox', { name: 'List entry' }), '1C351.c')
    await user.type(within(first).getByRole('textbox', { name: 'Act Annex I was read in' }), '(EU) 2025/2003')
    await user.click(screen.getByRole('button', { name: 'Add a restriction' }))
    const second = screen.getByRole('group', { name: 'Restriction 2' })
    await user.selectOptions(within(second).getByRole('combobox', { name: 'Kind' }), 'gmo')
    await user.type(within(second).getByRole('textbox', { name: 'List entry' }), 'MŽP 2026/12')
    await user.selectOptions(within(second).getByRole('combobox', { name: 'Contained use category' }), '2')
    await submit(user)
    await waitFor(() => expect(onDone).toHaveBeenCalledOnce(), { timeout: 5000 })
    expect(calls).toHaveLength(1)
    expect(calls[0]?.url.pathname).toBe(`/api/v1/labs/${LAB_ID}/deposits/${DEPOSIT_ID}/accept/`)
    expect(calls[0]?.headers.get('X-CSRFToken')).toBe('test-token')
    expect(calls[0]?.body).toEqual({
      taxon: exempli.public_id,
      identified_on: '2026-01-10',
      identification_method: '16S rRNA gene sequence',
      risk_group: 2,
      animal_pathogenicity: 'unknown',
      plant_pathogenicity: 'pathogenic',
      isolation_source: 'garden  soil',
      country_of_origin: 'CZ',
      isolation_date: '2019-05',
      restrictions: [
        { kind: 'dual_use', reference: '1C351.c', act: '(EU) 2025/2003', gmo_category: null },
        { kind: 'gmo', reference: 'MŽP 2026/12', act: '', gmo_category: 2 },
      ],
    })
  })

  it('offers the country the deposit states', async () => {
    await setup('CZ')
    expect(select('Country of origin')).toHaveValue('CZ')
  })

  it('picks the taxon in the combobox by keyboard, synonyms marked', async () => {
    const { user } = await setup()
    const taxon = select('Taxon')
    await user.click(taxon)
    await user.keyboard('exem')
    const listbox = await screen.findByRole('listbox', undefined, { timeout: 30_000 })
    expect(within(listbox).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Testella exempli Doe 2001 (species)',
      'Fictivibrio exempli  (synonym, species)',
    ])
    await user.keyboard('{ArrowDown}{ArrowDown}')
    expect(taxon).toHaveAttribute('aria-activedescendant', expect.stringMatching(/option-1$/))
    await user.keyboard('{Enter}')
    expect(taxon).toHaveValue('Fictivibrio exempli')
    expect(taxon).toHaveAttribute('aria-expanded', 'false')
  })

  it('refuses a form without the required fields, without a request, focusing the first', async () => {
    const calls = recordRequests('post', PATH)
    const { user } = await setup()
    await submit(user)
    expect(select('Taxon')).toHaveAccessibleDescription('Type part of the name, then choose. Choose a taxon')
    expect(select('Taxon')).toHaveFocus()
    expect(select('Risk group')).toHaveAccessibleDescription(/Choose a risk group$/)
    expect(select('Risk group')).toHaveAttribute('aria-invalid', 'true')
    expect(calls).toHaveLength(0)
  })

  it('asks for the act of a dual-use item and the category of a GMO before sending', async () => {
    const calls = recordRequests('post', PATH)
    const { user } = await setup()
    await fillRequired(user)
    await user.click(screen.getByRole('button', { name: 'Add a restriction' }))
    const row = screen.getByRole('group', { name: 'Restriction 1' })
    await user.selectOptions(within(row).getByRole('combobox', { name: 'Kind' }), 'dual_use')
    await user.type(within(row).getByRole('textbox', { name: 'List entry' }), '1C351.c')
    await submit(user)
    const act = within(row).getByRole('textbox', { name: 'Act Annex I was read in' })
    expect(act).toHaveAttribute('aria-invalid', 'true')
    expect(act).toHaveFocus()
    expect(calls).toHaveLength(0)
  })

  it('sends nothing with the last valid date while the field shows an invalid one (#111)', async () => {
    const calls = mockApi('post', PATH, makeDeposit({ status: 'accepted' }))
    const { user } = await setup()
    await fillRequired(user)
    const cases: readonly (readonly [string, string, readonly string[], string])[] = [
      ['Identified on', '2026-01-10', ['2026-13-45', '10.1.2026', '2026-01'], 'Enter a date as YYYY-MM-DD'],
      ['Isolation date', '2019-05', ['2019-5', '19-05-01', '2019-05-01x'], 'Use YYYY, YYYY-MM or YYYY-MM-DD'],
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

  it('shows the risk group 4 refusal on the risk group, focused, in its own words', async () => {
    // The domain code on top, as the API sends it for this refusal.
    mockApiError('post', PATH, 400, { ...problem(400, { code: 'risk_group_4_refused', detail: 'server words' }), errors: [{ attr: 'risk_group', code: 'risk_group_4_refused', detail: 'server words' }] })
    const { user } = await setup()
    await fillRequired(user)
    await user.selectOptions(select('Risk group'), '4')
    await submit(user)
    await waitFor(() => expect(select('Risk group')).toHaveAttribute('aria-invalid', 'true'), { timeout: 5000 })
    expect(select('Risk group')).toHaveAccessibleDescription(/The collection does not hold risk group 4 agents\.$/)
    expect(select('Risk group')).toHaveFocus()
    expect(screen.queryByText('server words')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('puts the permit refusal on the restriction it is about, naming the permit', async () => {
    mockApiError('post', PATH, 422, {
      ...problem(422, { code: 'lab_authorisation_required', detail: 'server words' }),
      errors: [{ attr: 'restrictions.1.kind', code: 'lab_authorisation_required', detail: 'server words' }],
    })
    const { user } = await setup()
    await fillRequired(user)
    for (const [index, kind] of [
      [1, 'cz_rat'],
      [2, 'cz_vrat'],
    ] as const) {
      await user.click(screen.getByRole('button', { name: 'Add a restriction' }))
      const row = screen.getByRole('group', { name: `Restriction ${index}` })
      await user.selectOptions(within(row).getByRole('combobox', { name: 'Kind' }), kind)
      await user.type(within(row).getByRole('textbox', { name: 'List entry' }), `entry ${index}`)
    }
    await submit(user)
    const kind = within(screen.getByRole('group', { name: 'Restriction 2' })).getByRole('combobox', { name: 'Kind' })
    await waitFor(() => expect(kind).toHaveAttribute('aria-invalid', 'true'), { timeout: 5000 })
    expect(kind).toHaveAccessibleDescription(/no valid SÚJB permit for highly risky agents \(VRAT\)/)
    expect(kind).toHaveFocus()
    expect(within(screen.getByRole('group', { name: 'Restriction 1' })).getByRole('combobox', { name: 'Kind' })).toHaveAttribute('aria-invalid', 'false')
  })

  it.each([
    ['identification_method', () => field('Identification method')],
    ['isolation_date', () => field('Isolation date')],
    ['country_of_origin', () => select('Country of origin')],
    ['taxon', () => select('Taxon')],
  ])('puts a server error on %s and focuses it', async (attr, input) => {
    mockApiError('post', PATH, 400, validationProblem([{ attr, code: 'invalid', detail: 'Not like this.' }]))
    const { user } = await setup()
    await fillRequired(user)
    await submit(user)
    await waitFor(() => expect(input()).toHaveAttribute('aria-invalid', 'true'), { timeout: 5000 })
    expect(input()).toHaveAccessibleDescription(/Not like this\.$/)
    expect(input()).toHaveFocus()
  })

  it('puts a nested server error on the restriction field', async () => {
    mockApiError('post', PATH, 400, validationProblem([{ attr: 'restrictions.0.reference', code: 'invalid', detail: 'Enter an Annex I entry.' }]))
    const { user } = await setup()
    await fillRequired(user)
    await user.click(screen.getByRole('button', { name: 'Add a restriction' }))
    await user.type(within(screen.getByRole('group', { name: 'Restriction 1' })).getByRole('textbox', { name: 'List entry' }), 'x')
    await submit(user)
    const entry = within(screen.getByRole('group', { name: 'Restriction 1' })).getByRole('textbox', { name: 'List entry' })
    await waitFor(() => expect(entry).toHaveAccessibleDescription(/Enter an Annex I entry\.$/), { timeout: 5000 })
    expect(entry).toHaveFocus()
  })

  it.each([
    [403, 'You do not have permission to do that.'],
    [500, 'The server failed. Try again in a moment.'],
  ])('shows one safe message for a %i', async (status, text) => {
    allowConsole(/API error 500/)
    mockApiError('post', PATH, status, problem(status, { detail: 'internal detail' }))
    const { user } = await setup()
    await fillRequired(user)
    await submit(user)
    expect(await screen.findByRole('alert')).toHaveTextContent(text)
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(screen.queryByText('internal detail')).not.toBeInTheDocument()
  })

  it('keeps the focus on Accept while it sends, and sends once', async () => {
    const held = holdApi('post', PATH)
    const { user, client } = await setup()
    await fillRequired(user)
    const button = screen.getByRole('button', { name: 'Accept' })
    await user.click(button)
    await waitFor(() => expect(button).toHaveAttribute('aria-disabled', 'true'), { timeout: 5000 })
    expect(button).not.toBeDisabled()
    expect(button).toHaveFocus()
    await user.click(button)
    expect(client.isMutating()).toBe(1)
    expect(held.calls).toHaveLength(1)
    held.release(200, makeDeposit())
    await waitFor(() => expect(button).toHaveAttribute('aria-disabled', 'false'), { timeout: 5000 })
  })

  it('moves the focus to Add a restriction when a row is removed', async () => {
    const { user } = await setup()
    const add = screen.getByRole('button', { name: 'Add a restriction' })
    await user.click(add)
    await user.click(screen.getByRole('button', { name: 'Remove restriction 1' }))
    expect(screen.queryByRole('group', { name: 'Restriction 1' })).not.toBeInTheDocument()
    expect(add).toHaveFocus()
  })

  it('stops at ten restrictions with Add a restriction still focusable', async () => {
    const { user } = await setup()
    const add = screen.getByRole('button', { name: 'Add a restriction' })
    for (let i = 0; i < 11; i++) await user.click(add)
    expect(screen.getAllByRole('group', { name: /^Restriction \d+$/ })).toHaveLength(10)
    expect(add).toHaveAttribute('aria-disabled', 'true')
    expect(add).toHaveFocus()
  })
})
