import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeMedium, makeMtaTemplate, makeStrain, mediumBrief, makeTaxon, makeTerms, page, problem, validationProblem } from '@/test/factories'
import { holdApi, mockApi, mockApiError } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { strainKeys } from '../api/keys'
import { StrainOverview } from './StrainOverview'
import { StrainShell } from './StrainShell'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const STRAIN_ID = '00000000-0000-4000-8000-0000000000d1'
const DETAIL = '/api/v1/labs/{lab_public_id}/strains/{public_id}/'
const TERMS = '/api/v1/labs/{lab_public_id}/strains/{public_id}/terms/'
// Invented taxa: the tests pair them with restrictions and risk groups, which no real
// organism should be shown with unless the facts hold.
const mockia = makeTaxon({ public_id: '00000000-0000-4000-8000-0000000000c3', name: 'Mockia vulgaris' })
const exempli = { public_id: '00000000-0000-4000-8000-0000000000c1', name: 'Testella exempli', authority: 'Roe 1999', rank: 'species' as const, status: 'accepted' as const }
const GMO = {
  public_id: '00000000-0000-4000-8000-0000000000e1',
  kind: 'gmo' as const,
  reference: 'MŽP 2026/12',
  act: '',
  gmo_category: 2,
  created_at: '2026-02-01T10:00:00Z',
  ended_at: null,
  end_reason: '',
  end_proposal: null,
}

const strain = makeStrain({
  public_id: STRAIN_ID,
  accession_number: 'MYC 42',
  name_as_received: 'T. exempli T1',
  taxon: exempli,
  risk_group: 2,
  animal_pathogenicity: 'none_known',
  country_of_origin: 'CZ',
  isolation_date: '2019-05',
  created_at: '2026-01-10T23:30:00Z',
  identifications: [
    { public_id: '00000000-0000-4000-8000-0000000000f2', taxon: exempli, identified_on: '2026-03-01', method: 'MALDI-TOF MS', reason: 'confirmed', is_current: true, created_at: '2026-03-01T10:00:00Z' },
    { public_id: '00000000-0000-4000-8000-0000000000f1', taxon: { ...exempli, name: 'Testella sp.' }, identified_on: '2026-01-10', method: '16S', reason: 'Identification at accession', is_current: false, created_at: '2026-01-10T10:00:00Z' },
  ],
  restriction_history: [
    GMO,
    { ...GMO, public_id: '00000000-0000-4000-8000-0000000000e2', kind: 'cz_rat', reference: 'Příloha 2, bod 3', gmo_category: null, ended_at: '2026-04-01T10:00:00Z', end_reason: 'delisted' },
  ],
})

const mta = makeMtaTemplate({ code: 'STD', version: 2, title: 'Standard MTA' })
const teachingDenied = makeTerms({
  version: 2,
  mta,
  reason: 'The depositor withdrew teaching.',
  uses: [
    { use: 'research_noncommercial', decision: 'permit' },
    { use: 'teaching', decision: 'deny' },
    { use: 'research_commercial', decision: 'on_request' },
  ],
})
const terms = (versions = [teachingDenied, makeTerms({ is_active: false })]) => mockApi('get', TERMS, { deposit: null, versions })

/** The strain page's header with its Overview tab, as the page puts them together. */
const render = (canManage = true, canConfirm = false) =>
  renderWithProviders(
    <StrainShell labId={LAB_ID} strainId={STRAIN_ID} canManage={canManage}>
      {(s) => <StrainOverview labId={LAB_ID} strain={s} canManage={canManage} canConfirm={canConfirm} />}
    </StrainShell>,
  )

/** Opens the strain's action menu and picks an action. */
async function action(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(await screen.findByRole('button', { name: 'Actions for MYC 42' }))
  await user.click(await screen.findByRole('menuitem', { name }))
}

describe('StrainShell with the Overview tab', { timeout: 20_000 }, () => {
  it('shows the number, the taxon, the facts, the restrictions and the identification history', async () => {
    mockApi('get', DETAIL, strain)
    terms()
    await render()
    expect(screen.getByText('Loading the strain…')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { level: 1, name: 'MYC 42' })).toBeInTheDocument()
    // The header: the taxon, then the risk group, the active restrictions and the status as chips.
    expect(screen.getByText('Testella exempli', { selector: 'header i' }).closest('p')).toHaveTextContent('Testella exempli Roe 1999')
    const chips = screen.getByRole('list', { name: 'Biosafety and status' })
    expect(within(chips).getAllByRole('listitem').map((item) => item.textContent)).toEqual(['Risk group 2', 'GMO in contained use', 'Active'])
    const facts = Object.fromEntries(
      [...document.querySelectorAll('dt')].map((dt) => [dt.textContent, dt.nextElementSibling?.textContent]),
    )
    expect(facts).toEqual({
      'Name as received': 'T. exempli T1',
      Status: 'Active',
      'Risk group': '2',
      'Animal pathogenicity': 'No pathogenicity known',
      'Plant pathogenicity': 'Unknown',
      'Isolation source': 'Unknown',
      'Country of origin': 'Czechia',
      'Isolation date': '2019-05',
      Accessioned: '2026-01-10',
      Medium: 'Not recorded',
      Temperature: 'Not recorded',
      Atmosphere: 'Not recorded',
    })
    const current = screen.getByRole('table', { name: 'Current restrictions' })
    expect(within(current).getAllByRole('row')[1]).toHaveTextContent('GMO in contained useMŽP 2026/12, category II2026-02-01Propose to end')
    const ended = screen.getByRole('table', { name: 'Ended restrictions' })
    expect(within(ended).getAllByRole('row')[1]).toHaveTextContent('Risky agent (RAT)Příloha 2, bod 32026-02-012026-04-01: delisted')
    // Tables that may scroll sideways at 320 px are tab stops, so the keys can scroll them.
    for (const name of ['Current restrictions', 'Ended restrictions', 'Identification history']) {
      expect(screen.getByRole('region', { name: `${name} table` })).toHaveAttribute('tabindex', '0')
    }
    const history = screen.getByRole('table', { name: 'Identification history' })
    expect(within(history).getAllByRole('row').slice(1).map((row) => row.textContent)).toEqual([
      '2026-03-01 (current)Testella exempli Roe 1999MALDI-TOF MSconfirmed',
      '2026-01-10Testella sp. Roe 199916SIdentification at accession',
    ])
    // The terms in force, by their own read: what the strain may be used for, under which MTA.
    const uses = await screen.findByRole('table', { name: 'Uses of the terms in force' })
    expect(within(uses).getAllByRole('row').slice(1).map((row) => row.textContent)).toEqual([
      'Non-commercial researchPermitted',
      'TeachingNot permitted',
      'Commercial researchOn request to the depositor',
    ])
    expect(screen.getByText(/^Version 2, in force since/)).toHaveTextContent('Version 2, in force since 2026-01-01. MTA STD version 2, Standard MTA')
    // The server gave no deposit (the reader may not open deposits): no link to the MTA's page.
    expect(screen.queryByRole('link', { name: /MTA STD/ })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Every version of the terms' })).toHaveAttribute('href', `/labs/${LAB_ID}/strains/${STRAIN_ID}/terms`)
  })

  it('says when a strain has no terms, and a failed read of them leaves the rest', async () => {
    allowConsole(/API error 500/)
    mockApi('get', DETAIL, strain)
    terms([])
    const first = await render()
    expect(await screen.findByText('No terms of use are recorded: the strain came from no deposit.')).toBeInTheDocument()
    first.unmount()
    mockApiError('get', TERMS, 500)
    await render()
    expect(await screen.findByText(/Could not load the terms/)).toBeInTheDocument()
    expect(screen.getByRole('table', { name: 'Identification history' })).toBeInTheDocument()
  })

  it('offers no changes to a role that may only read', async () => {
    mockApi('get', DETAIL, strain)
    terms()
    await render(false)
    await screen.findByRole('heading', { level: 1, name: 'MYC 42' })
    expect(screen.queryByRole('button', { name: /^Actions/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: 'Reclassify' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /end restriction/i })).not.toBeInTheDocument()
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
    terms()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'MYC 42' })).toBeInTheDocument()
  })

  it('reclassifies by keyboard, and the answer becomes the strain on screen', async () => {
    mockApi('get', DETAIL, strain)
    terms()
    mockApi('get', '/api/v1/taxa/', page([mockia]))
    const reclassified = { ...strain, taxon: { ...mockia } }
    const calls = mockApi('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/reclassify/', reclassified)
    const { client } = await render()
    const user = userEvent.setup()
    // The menu button by keyboard: ArrowDown opens it on its first item, Enter picks it.
    const trigger = await screen.findByRole('button', { name: 'Actions for MYC 42' })
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu')
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    trigger.focus()
    await user.keyboard('{ArrowDown}')
    const menu = await screen.findByRole('menu', { name: 'Actions for MYC 42' })
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    expect(trigger).toHaveAttribute('aria-controls', menu.id)
    expect(within(menu).getAllByRole('menuitem').map((item) => item.textContent)).toEqual(['Reclassify', 'Change risk group', 'Add a restriction', 'Change growth conditions', 'Propose deaccession'])
    await waitFor(() => expect(within(menu).getByRole('menuitem', { name: 'Reclassify' })).toHaveFocus())
    await user.keyboard('{Enter}')
    const dialog = await screen.findByRole('dialog', { name: 'Reclassify MYC 42' })
    const taxon = within(dialog).getByRole('combobox', { name: 'Taxon' })
    await waitFor(() => expect(taxon).toHaveFocus())
    await user.keyboard('vulg')
    await screen.findByRole('option', { name: /Mockia vulgaris/ }, { timeout: 4000 })
    await user.keyboard('{ArrowDown}{Enter}')
    await user.type(within(dialog).getByRole('textbox', { name: 'Method' }), 'MALDI-TOF MS')
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'the sequence differs')
    await user.click(within(dialog).getByRole('button', { name: 'Save identification' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ taxon: mockia.public_id, identified_on: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/), method: 'MALDI-TOF MS', reason: 'the sequence differs' })
    expect(client.getQueryData(strainKeys.detail(LAB_ID, STRAIN_ID))).toEqual(reclassified)
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('reclassifies nothing on the last valid date while the field shows an invalid one (#111)', async () => {
    mockApi('get', DETAIL, strain)
    terms()
    mockApi('get', '/api/v1/taxa/', page([mockia]))
    const calls = mockApi('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/reclassify/', strain)
    await render()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Actions for MYC 42' }))
    await user.click(await screen.findByRole('menuitem', { name: 'Reclassify' }))
    const dialog = await screen.findByRole('dialog', { name: 'Reclassify MYC 42' })
    const taxon = within(dialog).getByRole('combobox', { name: 'Taxon' })
    await waitFor(() => expect(taxon).toHaveFocus())
    await user.keyboard('vulg')
    await screen.findByRole('option', { name: /Mockia vulgaris/ }, { timeout: 4000 })
    await user.keyboard('{ArrowDown}{Enter}')
    await user.type(within(dialog).getByRole('textbox', { name: 'Method' }), 'MALDI-TOF MS')
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'the sequence differs')
    const day = within(dialog).getByRole('textbox', { name: 'Identified on' })
    for (const typed of ['2026-13-45', '12.10.2026']) {
      await user.clear(day)
      await user.type(day, typed)
      await user.click(within(dialog).getByRole('button', { name: 'Save identification' }))
      await waitFor(() => expect(day).toHaveAccessibleDescription(expect.stringContaining('Enter a date as YYYY-MM-DD')))
      expect(day).toHaveValue(typed)
      expect(calls).toHaveLength(0)
    }
  })

  it('shows the growth conditions of the strain on the Overview (V9)', async () => {
    const lb = makeMedium({ name: 'LB', composition_reference: 'DSMZ medium 381' })
    mockApi('get', DETAIL, { ...strain, growth: { medium: mediumBrief(lb), temperature_low_c: 25, temperature_high_c: 30, atmosphere: 'microaerophilic' } })
    terms()
    await render()
    await screen.findByRole('heading', { level: 1, name: 'MYC 42' })
    const facts = Object.fromEntries([...document.querySelectorAll('dt')].map((dt) => [dt.textContent, dt.nextElementSibling?.textContent]))
    expect(facts).toMatchObject({ Medium: 'LB, DSMZ medium 381', Temperature: '25 to 30 °C', Atmosphere: 'Microaerophilic' })
  })

  it('records the growth conditions of the strain with a reason, and shows them', async () => {
    const lb = makeMedium({ name: 'LB' })
    const grown = { ...strain, growth: { medium: mediumBrief(lb), temperature_low_c: 28, temperature_high_c: null, atmosphere: 'aerobic' as const } }
    mockApi('get', DETAIL, strain)
    mockApi('get', '/api/v1/labs/{lab_public_id}/media/', page([lb, makeMedium({ name: 'Old', retired_at: '2026-10-01T10:00:00Z' })]))
    terms()
    const calls = mockApi('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/growth/', grown)
    const { client } = await render()
    const user = userEvent.setup()
    await action(user, 'Change growth conditions')
    const dialog = await screen.findByRole('dialog', { name: 'Growth conditions of MYC 42' })
    const medium = within(dialog).getByRole('combobox', { name: 'Medium' })
    await waitFor(() => expect(medium).toHaveFocus())
    expect(within(medium).getAllByRole('option').map((o) => o.textContent)).toEqual(['No medium', 'LB'])
    await user.selectOptions(medium, 'LB')
    await user.type(within(dialog).getByRole('textbox', { name: 'Temperature °C' }), '28')
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Atmosphere' }), 'Aerobic')
    await user.click(within(dialog).getByRole('button', { name: 'Save growth conditions' }))
    await waitFor(() => expect(within(dialog).getByRole('textbox', { name: 'Reason' })).toHaveAccessibleDescription(/\S/))
    expect(calls).toHaveLength(0)
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'DSMZ medium 381 at 28 °C')
    await user.click(within(dialog).getByRole('button', { name: 'Save growth conditions' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ medium: lb.public_id, temperature_low_c: 28, temperature_high_c: null, atmosphere: 'aerobic', reason: 'DSMZ medium 381 at 28 °C' })
    expect(client.getQueryData(strainKeys.detail(LAB_ID, STRAIN_ID))).toEqual(grown)
    expect(await screen.findByText('28 °C')).toBeInTheDocument()
  })

  it('puts a temperature the server refuses on its field and keeps the dialog open', async () => {
    mockApi('get', DETAIL, strain)
    mockApi('get', '/api/v1/labs/{lab_public_id}/media/', page([]))
    terms()
    mockApiError('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/growth/', 400, validationProblem([{ attr: 'temperature_high_c', code: 'invalid', detail: 'The high end is below the low end.' }]))
    await render()
    const user = userEvent.setup()
    await action(user, 'Change growth conditions')
    const dialog = await screen.findByRole('dialog', { name: 'Growth conditions of MYC 42' })
    await user.type(within(dialog).getByRole('textbox', { name: 'Temperature °C' }), '30')
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'x')
    await user.click(within(dialog).getByRole('button', { name: 'Save growth conditions' }))
    await waitFor(() => expect(within(dialog).getByRole('textbox', { name: 'Up to °C' })).toHaveAccessibleDescription(/The high end is below the low end\.$/))
    expect(dialog).toBeInTheDocument()
  })

  it('refuses risk group 4 inside the dialog, on the field, and stays open', async () => {
    mockApi('get', DETAIL, strain)
    terms()
    mockApiError('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/risk-group/', 400, {
      ...problem(400, { code: 'risk_group_4_refused' }),
      errors: [{ attr: 'risk_group', code: 'risk_group_4_refused', detail: 'server words' }],
    })
    await render()
    const user = userEvent.setup()
    await action(user, 'Change risk group')
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

  it('puts a box cap refusal on the risk group, naming no box', async () => {
    mockApi('get', DETAIL, strain)
    terms()
    mockApiError('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/risk-group/', 400, {
      ...problem(400, { code: 'risk_group_above_box_cap' }),
      errors: [{ attr: 'risk_group', code: 'risk_group_above_box_cap', detail: 'server words' }],
    })
    await render()
    const user = userEvent.setup()
    await action(user, 'Change risk group')
    const dialog = await screen.findByRole('dialog', { name: 'Change the risk group of MYC 42' })
    const group = within(dialog).getByRole('combobox', { name: 'Risk group' })
    await user.selectOptions(group, '3')
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'reassessed')
    await user.click(within(dialog).getByRole('button', { name: 'Save risk group' }))
    await waitFor(() => expect(group).toHaveAccessibleDescription("A box holding this strain's vials does not allow this risk group. Move the vials first."))
    expect(group).toHaveFocus()
    expect(dialog).not.toHaveTextContent(/server words|Box/)
  })

  it('asks for a reason before changing the risk group, without a request', async () => {
    mockApi('get', DETAIL, strain)
    terms()
    const held = holdApi('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/risk-group/')
    await render()
    const user = userEvent.setup()
    await action(user, 'Change risk group')
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Save risk group' }))
    expect(within(dialog).getByRole('textbox', { name: 'Reason' })).toHaveAccessibleDescription('Stored for good with the change. Name no person. Say why')
    expect(held.calls).toHaveLength(0)
  })

  it('puts the permit refusal of an added VRAT on the kind', async () => {
    mockApi('get', DETAIL, strain)
    terms()
    mockApiError('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/restrictions/', 422, {
      ...problem(422, { code: 'lab_authorisation_required' }),
      errors: [{ attr: 'kind', code: 'lab_authorisation_required', detail: 'x' }],
    })
    await render()
    const user = userEvent.setup()
    await action(user, 'Add a restriction')
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
    terms()
    mockApiError('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/restrictions/', 400, validationProblem([{ attr: 'reference', code: 'unique', detail: 'The strain has this restriction already.' }]))
    await render()
    const user = userEvent.setup()
    await action(user, 'Add a restriction')
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByRole('textbox', { name: 'List entry' }), 'Příloha 2, bod 3')
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'listed')
    await user.click(within(dialog).getByRole('button', { name: 'Add restriction' }))
    const entry = within(dialog).getByRole('textbox', { name: 'List entry' })
    await waitFor(() => expect(entry).toHaveAccessibleDescription(/The strain has this restriction already\.$/))
    expect(entry).toHaveFocus()
  })

  it('proposes to end a restriction with a reason; it stays in force until a manager confirms', async () => {
    mockApi('get', DETAIL, strain)
    terms()
    const proposal = { public_id: '00000000-0000-4000-8000-0000000000e9', reason: 'destroyed', proposed_at: '2026-05-01T10:00:00Z', confirm_refusal: 'confirm_own_end_proposal' as const }
    const proposed = { ...strain, restriction_history: [{ ...GMO, end_proposal: proposal }, strain.restriction_history[1]!] }
    const calls = mockApi('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/restrictions/{restriction_id}/end-proposal/', proposed)
    await render(true, true)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Propose to end restriction MŽP 2026/12' }))
    const dialog = await screen.findByRole('dialog', { name: 'Propose to end the restriction MŽP 2026/12' })
    expect(dialog).toHaveAccessibleDescription(/stays in force until a manager other than you confirms/)
    const reason = within(dialog).getByRole('textbox', { name: 'Reason' })
    await waitFor(() => expect(reason).toHaveFocus())
    await user.keyboard('destroyed')
    await user.click(within(dialog).getByRole('button', { name: 'Propose' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.url.pathname).toBe(`/api/v1/labs/${LAB_ID}/strains/${STRAIN_ID}/restrictions/${GMO.public_id}/end-proposal/`)
    expect(calls[0]?.body).toEqual({ reason: 'destroyed' })
    const current = screen.getByRole('table', { name: 'Current restrictions' })
    expect(within(current).getByText(/Proposed 2026-05-01: destroyed/)).toBeInTheDocument()
    // The proposer is a manager too, but not the one who confirms.
    expect(within(current).getByText('You proposed it: a different manager confirms.')).toBeInTheDocument()
    expect(within(current).queryByRole('button', { name: /^Confirm the end/ })).not.toBeInTheDocument()
    expect(within(current).getByRole('button', { name: 'Withdraw the proposal to end restriction MŽP 2026/12' })).toBeInTheDocument()
  })

  it('a manager confirms the proposal they read, and the restriction ends', async () => {
    const proposal = { public_id: '00000000-0000-4000-8000-0000000000e9', reason: 'destroyed', proposed_at: '2026-05-01T10:00:00Z', confirm_refusal: null }
    mockApi('get', DETAIL, { ...strain, restriction_history: [{ ...GMO, end_proposal: proposal }, strain.restriction_history[1]!] })
    terms()
    const ended = { ...strain, restriction_history: strain.restriction_history.map((r) => ({ ...r, ended_at: r.ended_at ?? '2026-05-02T10:00:00Z', end_reason: r.end_reason || 'destroyed' })) }
    const calls = mockApi('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/restrictions/{restriction_id}/end-proposal/confirm/', ended)
    await render(true, true)
    const user = userEvent.setup()
    expect(await screen.findByText('Waiting for your confirmation.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Confirm the end of restriction MŽP 2026/12' }))
    const dialog = await screen.findByRole('alertdialog', { name: 'End the restriction MŽP 2026/12?' })
    expect(within(dialog).getByText('Reason given: destroyed')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'End restriction' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ proposal: proposal.public_id })
    expect(await screen.findByText('None. The agent is on no regulatory list.')).toBeInTheDocument()
    await waitFor(() => expect(document.activeElement).not.toBe(document.body))
    expect(screen.getByRole('heading', { level: 2, name: 'Restrictions' })).toHaveFocus()
  })

  it('a curator sees a proposal waiting for a manager and may withdraw it, never confirm it', async () => {
    const proposal = { public_id: '00000000-0000-4000-8000-0000000000e9', reason: 'destroyed', proposed_at: '2026-05-01T10:00:00Z', confirm_refusal: null }
    mockApi('get', DETAIL, { ...strain, restriction_history: [{ ...GMO, end_proposal: proposal }, strain.restriction_history[1]!] })
    terms()
    const calls = mockApi('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/restrictions/{restriction_id}/end-proposal/withdraw/', strain)
    await render(true, false)
    const user = userEvent.setup()
    expect(await screen.findByText('Waiting for a manager to confirm.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Confirm the end/ })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Withdraw the proposal to end restriction MŽP 2026/12' }))
    const dialog = await screen.findByRole('dialog', { name: 'Withdraw the proposal to end MŽP 2026/12' })
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'still listed')
    await user.click(within(dialog).getByRole('button', { name: 'Withdraw' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ proposal: proposal.public_id, reason: 'still listed' })
    expect(await screen.findByRole('button', { name: 'Propose to end restriction MŽP 2026/12' })).toBeInTheDocument()
  })

  it('says the proposal changed when another one is open now', async () => {
    const proposal = { public_id: '00000000-0000-4000-8000-0000000000e9', reason: 'destroyed', proposed_at: '2026-05-01T10:00:00Z', confirm_refusal: null }
    mockApi('get', DETAIL, { ...strain, restriction_history: [{ ...GMO, end_proposal: proposal }, strain.restriction_history[1]!] })
    terms()
    mockApiError('post', '/api/v1/labs/{lab_public_id}/strains/{public_id}/restrictions/{restriction_id}/end-proposal/confirm/', 409, problem(409, { code: 'end_proposal_changed' }))
    await render(true, true)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Confirm the end of restriction MŽP 2026/12' }))
    const dialog = await screen.findByRole('alertdialog', { name: 'End the restriction MŽP 2026/12?' })
    await user.click(within(dialog).getByRole('button', { name: 'End restriction' }))
    expect(await within(dialog).findByText('The proposal changed meanwhile. Close this and read it again before you decide.')).toBeInTheDocument()
  })
})
