import { screen, waitFor, within } from '@testing-library/react'
import userEvent, { type UserEvent } from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeStrain, makeTaxon, page, problem, validationProblem } from '@/test/factories'
import { holdApi, mockApi, mockApiError, recordRequests } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { strainKeys } from '../api/keys'
import type { Strain } from '../schemas'
import { CreateStrainForm } from './CreateStrainForm'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const PATH = '/api/v1/labs/{lab_public_id}/strains/'
const subtilis = makeTaxon({ public_id: '00000000-0000-4000-8000-0000000000c1', name: 'Bacillus subtilis', authority: '(Ehrenberg 1835) Cohn 1872' })
const vibrio = makeTaxon({ public_id: '00000000-0000-4000-8000-0000000000c2', name: 'Vibrio subtilis', status: 'synonym' })

async function setup() {
  mockApi('get', '/api/v1/taxa/', page([subtilis, vibrio]))
  const onCreated = vi.fn<(strain: Strain) => void>()
  const view = await renderWithProviders(<CreateStrainForm labId={LAB_ID} onCreated={onCreated} />)
  const user = userEvent.setup()
  return { ...view, user, onCreated, form: screen.getByRole('form', { name: 'Add a strain' }) }
}

const field = (name: string) => screen.getByRole('textbox', { name })
const select = (name: string) => screen.getByRole('combobox', { name })

/** The taxon by keyboard: type, ArrowDown to the first match, Enter. */
async function pickTaxon(user: UserEvent, text = 'subt') {
  await user.click(select('Taxon'))
  await user.keyboard(text)
  await screen.findByRole('option', { name: /Bacillus subtilis/ }, { timeout: 4000 })
  await user.keyboard('{ArrowDown}{Enter}')
}

async function fillRequired(user: UserEvent) {
  await pickTaxon(user)
  await user.type(field('Name as received'), 'B. subtilis 168')
  await user.clear(field('Identified on'))
  await user.type(field('Identified on'), '2026-01-10')
  await user.type(field('Identification method'), '16S rRNA gene sequence')
  await user.selectOptions(select('Risk group'), '2')
}

const submit = (user: UserEvent) => user.click(screen.getByRole('button', { name: 'Add strain' }))

// Long forms typed key by key, beside other test files: more than the default 5 s per test.
describe('CreateStrainForm', { timeout: 20_000 }, () => {
  it('sends the strain with its restrictions, the CSRF token, and goes to it', async () => {
    const created = makeStrain({ accession_number: 'MYC 1' })
    const calls = mockApi('post', PATH, created)
    const { user, client, onCreated } = await setup()
    client.setQueryData(strainKeys.list(LAB_ID, { limit: 25, offset: 0 }), page([]))
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
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(created))
    expect(calls).toHaveLength(1)
    expect(calls[0]?.url.pathname).toBe(`/api/v1/labs/${LAB_ID}/strains/`)
    expect(calls[0]?.headers.get('X-CSRFToken')).toBe('test-token')
    expect(calls[0]?.body).toEqual({
      taxon: subtilis.public_id,
      name_as_received: 'B. subtilis 168',
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
    expect(client.getQueryData(strainKeys.detail(LAB_ID, created.public_id))).toEqual(created)
    expect(client.getQueryState(strainKeys.list(LAB_ID, { limit: 25, offset: 0 }))?.isInvalidated).toBe(true)
  })

  it('picks the taxon in the combobox by keyboard, synonyms marked', async () => {
    const { user } = await setup()
    const taxon = select('Taxon')
    await user.click(taxon)
    await user.keyboard('subt')
    const listbox = await screen.findByRole('listbox', undefined, { timeout: 4000 })
    expect(within(listbox).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Bacillus subtilis (Ehrenberg 1835) Cohn 1872 (species)',
      'Vibrio subtilis  (synonym, species)',
    ])
    await user.keyboard('{ArrowDown}{ArrowDown}')
    expect(taxon).toHaveAttribute('aria-activedescendant', expect.stringMatching(/option-1$/))
    await user.keyboard('{Enter}')
    expect(taxon).toHaveValue('Vibrio subtilis')
    expect(taxon).toHaveAttribute('aria-expanded', 'false')
  })

  it('refuses a form without the required fields, without a request, focusing the first', async () => {
    const calls = recordRequests('post', PATH)
    const { user } = await setup()
    await submit(user)
    expect(select('Taxon')).toHaveAccessibleDescription('Type part of the name, then choose. Choose a taxon')
    expect(select('Taxon')).toHaveFocus()
    expect(field('Name as received')).toHaveAccessibleDescription('As the depositor gave it. It cannot be changed later. Enter the name as received')
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

  it('shows the risk group 4 refusal on the risk group, focused, in its own words', async () => {
    // The domain code on top, as the API sends it for this refusal.
    mockApiError('post', PATH, 400, { ...problem(400, { code: 'risk_group_4_refused', detail: 'server words' }), errors: [{ attr: 'risk_group', code: 'risk_group_4_refused', detail: 'server words' }] })
    const { user } = await setup()
    await fillRequired(user)
    await user.selectOptions(select('Risk group'), '4')
    await submit(user)
    await waitFor(() => expect(select('Risk group')).toHaveAttribute('aria-invalid', 'true'))
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
    await waitFor(() => expect(kind).toHaveAttribute('aria-invalid', 'true'))
    expect(kind).toHaveAccessibleDescription(/no valid SÚJB permit for highly risky agents \(VRAT\)/)
    expect(kind).toHaveFocus()
    expect(within(screen.getByRole('group', { name: 'Restriction 1' })).getByRole('combobox', { name: 'Kind' })).toHaveAttribute('aria-invalid', 'false')
  })

  it.each([
    ['name_as_received', () => field('Name as received')],
    ['isolation_date', () => field('Isolation date')],
    ['country_of_origin', () => select('Country of origin')],
    ['taxon', () => select('Taxon')],
  ])('puts a server error on %s and focuses it', async (attr, input) => {
    mockApiError('post', PATH, 400, validationProblem([{ attr, code: 'invalid', detail: 'Not like this.' }]))
    const { user } = await setup()
    await fillRequired(user)
    await submit(user)
    await waitFor(() => expect(input()).toHaveAttribute('aria-invalid', 'true'))
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
    await waitFor(() => expect(entry).toHaveAccessibleDescription(/Enter an Annex I entry\.$/))
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

  it('keeps the focus on Add strain while it sends, and sends once', async () => {
    const held = holdApi('post', PATH)
    const { user, client } = await setup()
    await fillRequired(user)
    const button = screen.getByRole('button', { name: 'Add strain' })
    await user.click(button)
    await waitFor(() => expect(button).toHaveAttribute('aria-disabled', 'true'))
    expect(button).not.toBeDisabled()
    expect(button).toHaveFocus()
    await user.click(button)
    expect(client.isMutating()).toBe(1)
    expect(held.calls).toHaveLength(1)
    held.release(201, makeStrain())
    await waitFor(() => expect(button).toHaveAttribute('aria-disabled', 'false'))
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
