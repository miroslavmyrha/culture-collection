import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeStrain, makeTaxon, page, problem, validationProblem } from '@/test/factories'
import { holdApi, mockApi, mockApiError } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { strainKeys } from '../api/keys'
import { StrainDetail } from './StrainDetail'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const STRAIN_ID = '00000000-0000-4000-8000-0000000000d1'
const DETAIL = '/api/v1/labs/{lab_public_id}/strains/{public_id}/'
const coli = makeTaxon({ public_id: '00000000-0000-4000-8000-0000000000c3', name: 'Escherichia coli' })
const subtilis = { public_id: '00000000-0000-4000-8000-0000000000c1', name: 'Bacillus subtilis', authority: 'Cohn 1872', rank: 'species' as const, status: 'accepted' as const }
const GMO = {
  public_id: '00000000-0000-4000-8000-0000000000e1',
  kind: 'gmo' as const,
  reference: 'MŽP 2026/12',
  act: '',
  gmo_category: 2,
  created_at: '2026-02-01T10:00:00Z',
  ended_at: null,
  end_reason: '',
}

const strain = makeStrain({
  public_id: STRAIN_ID,
  accession_number: 'MYC 42',
  name_as_received: 'B. subtilis 168',
  taxon: subtilis,
  risk_group: 2,
  animal_pathogenicity: 'none_known',
  country_of_origin: 'CZ',
  isolation_date: '2019-05',
  created_at: '2026-01-10T23:30:00Z',
  identifications: [
    { public_id: '00000000-0000-4000-8000-0000000000f2', taxon: subtilis, identified_on: '2026-03-01', method: 'MALDI-TOF MS', reason: 'confirmed', is_current: true, created_at: '2026-03-01T10:00:00Z' },
    { public_id: '00000000-0000-4000-8000-0000000000f1', taxon: { ...subtilis, name: 'Bacillus sp.' }, identified_on: '2026-01-10', method: '16S', reason: 'Identification at accession', is_current: false, created_at: '2026-01-10T10:00:00Z' },
  ],
  restriction_history: [
    GMO,
    { ...GMO, public_id: '00000000-0000-4000-8000-0000000000e2', kind: 'cz_rat', reference: 'Příloha 2, bod 3', gmo_category: null, ended_at: '2026-04-01T10:00:00Z', end_reason: 'delisted' },
  ],
})

const render = (canManage = true) => renderWithProviders(<StrainDetail labId={LAB_ID} strainId={STRAIN_ID} canManage={canManage} />)

describe('StrainDetail', { timeout: 20_000 }, () => {
  it('shows the number, the taxon, the facts, the restrictions and the identification history', async () => {
    mockApi('get', DETAIL, strain)
    await render()
    expect(screen.getByText('Loading the strain…')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { level: 1, name: 'MYC 42' })).toBeInTheDocument()
    expect(document.title).toBe('MYC 42 | Culture collection')
    const facts = Object.fromEntries(
      [...document.querySelectorAll('dt')].map((dt) => [dt.textContent, dt.nextElementSibling?.textContent]),
    )
    expect(facts).toEqual({
      'Name as received': 'B. subtilis 168',
      Status: 'Active',
      'Risk group': '2',
      'Animal pathogenicity': 'No pathogenicity known',
      'Plant pathogenicity': 'Unknown',
      'Isolation source': 'Unknown',
      'Country of origin': 'Czechia',
      'Isolation date': '2019-05',
      Accessioned: '2026-01-10',
    })
    const current = screen.getByRole('table', { name: 'Current restrictions' })
    expect(within(current).getAllByRole('row')[1]).toHaveTextContent('GMO in contained useMŽP 2026/12, category II2026-02-01End')
    const ended = screen.getByRole('table', { name: 'Ended restrictions' })
    expect(within(ended).getAllByRole('row')[1]).toHaveTextContent('Risky agent (RAT)Příloha 2, bod 32026-02-012026-04-01: delisted')
    // Tables that may scroll sideways at 320 px are tab stops, so the keys can scroll them.
    for (const name of ['Current restrictions', 'Ended restrictions', 'Identification history']) {
      expect(screen.getByRole('region', { name: `${name} table` })).toHaveAttribute('tabindex', '0')
    }
    const history = screen.getByRole('table', { name: 'Identification history' })
    expect(within(history).getAllByRole('row').slice(1).map((row) => row.textContent)).toEqual([
      '2026-03-01 (current)Bacillus subtilis Cohn 1872MALDI-TOF MSconfirmed',
      '2026-01-10Bacillus sp. Cohn 187216SIdentification at accession',
    ])
  })

  it('offers no changes to a role that may only read', async () => {
    mockApi('get', DETAIL, strain)
    await render(false)
    await screen.findByRole('heading', { level: 1, name: 'MYC 42' })
    expect(screen.queryByRole('button', { name: 'Reclassify' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /End restriction/ })).not.toBeInTheDocument()
  })

  it('says a strain it cannot find is not found, with its title', async () => {
    mockApiError('get', DETAIL, 404, problem(404, { code: 'not_found' }))
    await render()
    expect(await screen.findByRole('heading', { level: 1, name: 'Strain not found' })).toBeInTheDocument()
    expect(document.title).toBe('Strain not found | Culture collection')
  })

  it('shows a failed load with a retry, titled', async () => {
    allowConsole(/API error 500/)
    mockApiError('get', DETAIL, 500)
    await render()
    expect(await screen.findByText(/Could not load the strain/)).toBeInTheDocument()
    expect(document.title).toBe('Could not load the strain | Culture collection')
    mockApi('get', DETAIL, strain)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'MYC 42' })).toBeInTheDocument()
  })

  it('reclassifies by keyboard, and the answer becomes the strain on screen', async () => {
    mockApi('get', DETAIL, strain)
    mockApi('get', '/api/v1/taxa/', page([coli]))
    const reclassified = { ...strain, taxon: { ...coli } }
    const calls = mockApi('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/reclassify/', reclassified)
    const { client } = await render()
    const user = userEvent.setup()
    const trigger = await screen.findByRole('button', { name: 'Reclassify' })
    trigger.focus()
    await user.keyboard('{Enter}')
    const dialog = await screen.findByRole('dialog', { name: 'Reclassify MYC 42' })
    const taxon = within(dialog).getByRole('combobox', { name: 'Taxon' })
    await waitFor(() => expect(taxon).toHaveFocus())
    await user.keyboard('coli')
    await screen.findByRole('option', { name: /Escherichia coli/ }, { timeout: 4000 })
    await user.keyboard('{ArrowDown}{Enter}')
    await user.type(within(dialog).getByRole('textbox', { name: 'Method' }), 'MALDI-TOF MS')
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'the sequence differs')
    await user.click(within(dialog).getByRole('button', { name: 'Save identification' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ taxon: coli.public_id, identified_on: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/), method: 'MALDI-TOF MS', reason: 'the sequence differs' })
    expect(client.getQueryData(strainKeys.detail(LAB_ID, STRAIN_ID))).toEqual(reclassified)
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('refuses risk group 4 inside the dialog, on the field, and stays open', async () => {
    mockApi('get', DETAIL, strain)
    mockApiError('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/risk-group/', 400, {
      ...problem(400, { code: 'risk_group_4_refused' }),
      errors: [{ attr: 'risk_group', code: 'risk_group_4_refused', detail: 'server words' }],
    })
    await render()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Change risk group' }))
    const dialog = await screen.findByRole('dialog', { name: 'Change the risk group of MYC 42' })
    const group = within(dialog).getByRole('combobox', { name: 'Risk group' })
    expect(group).toHaveValue('2')
    await user.selectOptions(group, '4')
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'reassessed')
    await user.click(within(dialog).getByRole('button', { name: 'Save risk group' }))
    await waitFor(() => expect(group).toHaveAccessibleDescription('The collection does not hold risk group 4 agents.'))
    expect(group).toHaveFocus()
    expect(dialog).toBeInTheDocument()
  })

  it('asks for a reason before changing the risk group, without a request', async () => {
    mockApi('get', DETAIL, strain)
    const held = holdApi('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/risk-group/')
    await render()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Change risk group' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Save risk group' }))
    expect(within(dialog).getByRole('textbox', { name: 'Reason' })).toHaveAccessibleDescription('Stored for good with the change. Name no person. Say why')
    expect(held.calls).toHaveLength(0)
  })

  it('puts the permit refusal of an added VRAT on the kind', async () => {
    mockApi('get', DETAIL, strain)
    mockApiError('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/restrictions/', 422, {
      ...problem(422, { code: 'lab_authorisation_required' }),
      errors: [{ attr: 'kind', code: 'lab_authorisation_required', detail: 'x' }],
    })
    await render()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Add a restriction' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add a restriction to MYC 42' })
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Kind' }), 'cz_vrat')
    await user.type(within(dialog).getByRole('textbox', { name: 'List entry' }), 'Příloha 1, bod 2')
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'listed')
    await user.click(within(dialog).getByRole('button', { name: 'Add restriction' }))
    const kind = within(dialog).getByRole('combobox', { name: 'Kind' })
    await waitFor(() => expect(kind).toHaveAccessibleDescription(/no valid SÚJB permit/))
    expect(kind).toHaveFocus()
  })

  it('maps a field error of an added restriction to its field', async () => {
    mockApi('get', DETAIL, strain)
    mockApiError('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/restrictions/', 400, validationProblem([{ attr: 'reference', code: 'unique', detail: 'The strain has this restriction already.' }]))
    await render()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Add a restriction' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByRole('textbox', { name: 'List entry' }), 'Příloha 2, bod 3')
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'listed')
    await user.click(within(dialog).getByRole('button', { name: 'Add restriction' }))
    const entry = within(dialog).getByRole('textbox', { name: 'List entry' })
    await waitFor(() => expect(entry).toHaveAccessibleDescription(/The strain has this restriction already\.$/))
    expect(entry).toHaveFocus()
  })

  it('ends a restriction with a reason; the focus goes to the next control when its row is gone', async () => {
    mockApi('get', DETAIL, strain)
    const ended = { ...strain, restriction_history: strain.restriction_history.map((r) => ({ ...r, ended_at: r.ended_at ?? '2026-05-01T10:00:00Z', end_reason: r.end_reason || 'destroyed' })) }
    const calls = mockApi('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/restrictions/{restriction_id}/end/', ended)
    await render()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'End restriction MŽP 2026/12' }))
    const dialog = await screen.findByRole('dialog', { name: 'End the restriction MŽP 2026/12' })
    const reason = within(dialog).getByRole('textbox', { name: 'Reason' })
    await waitFor(() => expect(reason).toHaveFocus())
    await user.keyboard('destroyed')
    await user.click(within(dialog).getByRole('button', { name: 'End restriction' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.url.pathname).toBe(`/api/v1/labs/${LAB_ID}/strains/${STRAIN_ID}/restrictions/${GMO.public_id}/end/`)
    expect(calls[0]?.body).toEqual({ reason: 'destroyed' })
    expect(await screen.findByText('None. The agent is on no regulatory list.')).toBeInTheDocument()
    await waitFor(() => expect(document.activeElement).not.toBe(document.body))
    expect(screen.getByRole('heading', { level: 2, name: 'Restrictions' })).toHaveFocus()
  })
})
