import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeStrain, makeTerms, page, problem } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { StrainOverview } from './StrainOverview'
import { StrainShell } from './StrainShell'

// A strain leaves the collection (#20): one person for a strain that is not regulated, two for
// a regulated one (a curator or manager proposes, a manager other than the proposer confirms).

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const STRAIN_ID = '00000000-0000-4000-8000-0000000000d1'
const DETAIL = '/api/v1/labs/{lab_public_id}/strains/{public_id}/'
const TERMS = '/api/v1/labs/{lab_public_id}/strains/{public_id}/terms/'
const SHIPMENTS = '/api/v1/labs/{lab_public_id}/strains/{public_id}/shipments/'
const LEAVE = '/api/v1/labs/{lab_public_id}/strains/{public_id}/deaccession/'
const PROPOSE = '/api/v1/labs/{lab_public_id}/strains/{public_id}/deaccession-proposal/'
const CONFIRM = '/api/v1/labs/{lab_public_id}/strains/{public_id}/deaccession-proposal/confirm/'
const WITHDRAW = '/api/v1/labs/{lab_public_id}/strains/{public_id}/deaccession-proposal/withdraw/'

// Invented taxon and list entries: no real organism is shown with a restriction here.
const restriction = (kind: 'gmo' | 'quarantine_pest') => ({
  public_id: kind === 'gmo' ? '00000000-0000-4000-8000-0000000000e1' : '00000000-0000-4000-8000-0000000000e2',
  kind,
  reference: kind === 'gmo' ? 'MŽP 2026/12' : 'Annex II, Part B',
  act: '',
  gmo_category: kind === 'gmo' ? 2 : null,
  created_at: '2026-02-01T10:00:00Z',
  ended_at: null,
  end_reason: '',
  end_proposal: null,
})
const plain = makeStrain({ public_id: STRAIN_ID, accession_number: 'MYC 42' })
const regulated = makeStrain({ public_id: STRAIN_ID, accession_number: 'MYC 42', restriction_history: [restriction('gmo')] })
const pest = makeStrain({ public_id: STRAIN_ID, accession_number: 'MYC 42', restriction_history: [restriction('quarantine_pest')] })
const PROPOSAL = {
  public_id: '00000000-0000-4000-8000-0000000000e9',
  cause: 'contaminated' as const,
  reason: 'Mixed culture on every plate.',
  final_use: '' as const,
  proposed_at: '2026-10-20T10:00:00Z',
  confirm_refusal: null,
}
const gone = (from = plain) =>
  ({
    ...from,
    status: 'deaccessioned' as const,
    deaccession: { deaccessioned_at: '2026-10-21T10:00:00Z', cause: 'non_viable' as const, reason: 'No growth after three revivals.', final_use: '' as const },
    deaccession_proposal: null,
  }) satisfies typeof plain
const SHIPPED = { request: '00000000-0000-4000-8000-0000000000a1', number: '2026/3', institution: 'Example Institute of Microbiology', country: 'DE', shipped_at: '2026-06-01T10:00:00Z', vials: 2 }

function render(strain: typeof plain, { canManage = true, canConfirmLeave = false } = {}) {
  mockApi('get', DETAIL, strain)
  mockApi('get', TERMS, { deposit: null, versions: [makeTerms()] })
  // In main, as the layout puts every page: focus falls back to its h1.
  return renderWithProviders(
    <main>
      <StrainShell labId={LAB_ID} strainId={STRAIN_ID} canManage={canManage}>
        {(s) => <StrainOverview labId={LAB_ID} strain={s} canManage={canManage} canConfirm={canConfirmLeave} canConfirmLeave={canConfirmLeave} />}
      </StrainShell>
    </main>,
  )
}

async function menu(user: ReturnType<typeof userEvent.setup>, item: string) {
  await user.click(await screen.findByRole('button', { name: 'Actions for MYC 42' }))
  await user.click(await screen.findByRole('menuitem', { name: item }))
}

describe('deaccession on the strain page', { timeout: 20_000 }, () => {
  it('a curator deaccessions a strain that is not regulated; it then shows how it left and where its vials went', async () => {
    const calls = mockApi('post', LEAVE, gone())
    const shipments = mockApi('get', SHIPMENTS, page([SHIPPED]))
    await render(plain)
    const user = userEvent.setup()
    await menu(user, 'Deaccession')
    const dialog = await screen.findByRole('alertdialog', { name: 'Deaccession MYC 42?' })
    expect(dialog).toHaveAccessibleDescription(/leaves the collection for good. Its open requests are cancelled and its vials still in stock are marked for destruction/)
    // A destructive dialog opens on Cancel.
    await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus())
    // No cause yet: the form says so and nothing is sent.
    await user.click(within(dialog).getByRole('button', { name: 'Deaccession' }))
    expect(await within(dialog).findByText('Choose why the strain leaves')).toBeInTheDocument()
    expect(calls).toHaveLength(0)
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Cause' }), 'No longer grows')
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), '  No growth after three revivals. ')
    await user.click(within(dialog).getByRole('button', { name: 'Deaccession' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ cause: 'non_viable', reason: 'No growth after three revivals.', final_use: '' })
    // Deaccessioned is terminal: no actions any more, the status chip says it.
    expect(screen.queryByRole('button', { name: 'Actions for MYC 42' })).not.toBeInTheDocument()
    expect(within(screen.getByRole('list', { name: 'Biosafety and status' })).getByText('Deaccessioned')).toBeInTheDocument()
    const left = screen.getByRole('region', { name: 'Deaccession' })
    expect(left).toHaveTextContent('Left the collection2026-10-21CauseNo longer growsReasonNo growth after three revivals.')
    const table = await screen.findByRole('table', { name: 'Shipments' })
    expect(within(table).getAllByRole('row')[1]).toHaveTextContent('2026/3Example Institute of MicrobiologyGermany2026-06-012')
    expect(within(table).getByRole('link', { name: '2026/3' })).toHaveAttribute('href', `/labs/${LAB_ID}/requests/${SHIPPED.request}`)
    expect(shipments).toHaveLength(1)
  })

  it('a deaccessioned strain without shipments says so', async () => {
    mockApi('get', SHIPMENTS, page([]))
    await render(gone())
    expect(await screen.findByText('No vial of this strain was distributed.')).toBeInTheDocument()
  })

  it('a regulated strain is proposed, and a quarantine pest states its final use', async () => {
    const calls = mockApi('post', PROPOSE, { ...pest, deaccession_proposal: { ...PROPOSAL, final_use: 'destruction', confirm_refusal: 'confirm_own_deaccession' } })
    await render(pest)
    const user = userEvent.setup()
    expect(await screen.findByRole('heading', { level: 1, name: 'MYC 42' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Actions for MYC 42' }))
    expect(screen.queryByRole('menuitem', { name: 'Deaccession' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('menuitem', { name: 'Propose deaccession' }))
    const dialog = await screen.findByRole('dialog', { name: 'Propose to deaccession MYC 42' })
    expect(dialog).toHaveAccessibleDescription(/stays in the collection until a manager other than you confirms/)
    await waitFor(() => expect(within(dialog).getByRole('combobox', { name: 'Cause' })).toHaveFocus())
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Cause' }), 'Contaminated')
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'Mixed culture on every plate.')
    await user.click(within(dialog).getByRole('button', { name: 'Propose' }))
    expect(await within(dialog).findByText(/Choose the final use/)).toBeInTheDocument()
    expect(calls).toHaveLength(0)
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Final use' }), 'Destruction')
    await user.click(within(dialog).getByRole('button', { name: 'Propose' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ cause: 'contaminated', reason: 'Mixed culture on every plate.', final_use: 'destruction' })
    const proposed = screen.getByRole('region', { name: 'Proposed deaccession' })
    expect(proposed).toHaveTextContent('Final useDestruction')
    expect(within(proposed).getByText('You proposed it: a different manager confirms.')).toBeInTheDocument()
    expect(within(proposed).queryByRole('button', { name: 'Confirm deaccession' })).not.toBeInTheDocument()
    // A proposal waits: the menu offers no second one.
    await user.click(screen.getByRole('button', { name: 'Actions for MYC 42' }))
    expect(screen.queryByRole('menuitem', { name: /deaccession/i })).not.toBeInTheDocument()
  })

  it('a strain that is not a quarantine pest is asked no final use', async () => {
    await render(regulated)
    const user = userEvent.setup()
    await menu(user, 'Propose deaccession')
    const dialog = await screen.findByRole('dialog', { name: 'Propose to deaccession MYC 42' })
    expect(within(dialog).queryByRole('combobox', { name: 'Final use' })).not.toBeInTheDocument()
  })

  it('another manager confirms the proposal they read', async () => {
    const calls = mockApi('post', CONFIRM, gone(regulated))
    mockApi('get', SHIPMENTS, page([]))
    await render({ ...regulated, deaccession_proposal: PROPOSAL }, { canConfirmLeave: true })
    const user = userEvent.setup()
    const proposed = await screen.findByRole('region', { name: 'Proposed deaccession' })
    expect(within(proposed).getByText('Waiting for your confirmation.')).toBeInTheDocument()
    await user.click(within(proposed).getByRole('button', { name: 'Confirm deaccession' }))
    const dialog = await screen.findByRole('alertdialog', { name: 'Deaccession MYC 42?' })
    expect(within(dialog).getByText('Reason given: Mixed culture on every plate.')).toBeInTheDocument()
    expect(within(dialog).getByText('Cause: Contaminated')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Deaccession' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ proposal: PROPOSAL.public_id })
    expect(await screen.findByRole('region', { name: 'Deaccession' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Proposed deaccession' })).not.toBeInTheDocument()
  })

  it('a manager who proposed it is not offered the confirmation', async () => {
    await render({ ...regulated, deaccession_proposal: { ...PROPOSAL, confirm_refusal: 'confirm_own_deaccession' } }, { canConfirmLeave: true })
    const proposed = await screen.findByRole('region', { name: 'Proposed deaccession' })
    expect(within(proposed).getByText('You proposed it: a different manager confirms.')).toBeInTheDocument()
    expect(within(proposed).queryByRole('button', { name: 'Confirm deaccession' })).not.toBeInTheDocument()
    expect(within(proposed).getByRole('button', { name: 'Withdraw the proposal' })).toBeInTheDocument()
  })

  it('a curator sees who confirms and may withdraw the proposal with a reason', async () => {
    const calls = mockApi('post', WITHDRAW, regulated)
    await render({ ...regulated, deaccession_proposal: PROPOSAL })
    const user = userEvent.setup()
    const proposed = await screen.findByRole('region', { name: 'Proposed deaccession' })
    expect(within(proposed).getByText('Waiting for a manager to confirm.')).toBeInTheDocument()
    expect(within(proposed).queryByRole('button', { name: 'Confirm deaccession' })).not.toBeInTheDocument()
    await user.click(within(proposed).getByRole('button', { name: 'Withdraw the proposal' }))
    const dialog = await screen.findByRole('dialog', { name: 'Withdraw the proposal to deaccession MYC 42' })
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'It grew after all.')
    await user.click(within(dialog).getByRole('button', { name: 'Withdraw' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ proposal: PROPOSAL.public_id, reason: 'It grew after all.' })
    expect(screen.queryByRole('region', { name: 'Proposed deaccession' })).not.toBeInTheDocument()
    // The button that opened the dialog is gone with its section: focus goes to the page's h1.
    await waitFor(() => expect(screen.getByRole('heading', { level: 1, name: 'MYC 42' })).toHaveFocus())
  })

  it('says inside the dialog why the confirmation was refused', async () => {
    allowConsole(/API error 409/)
    mockApiError('post', CONFIRM, 409, problem(409, { code: 'request_awaits_confirmation' }))
    await render({ ...regulated, deaccession_proposal: PROPOSAL }, { canConfirmLeave: true })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Confirm deaccession' }))
    const dialog = await screen.findByRole('alertdialog', { name: 'Deaccession MYC 42?' })
    await user.click(within(dialog).getByRole('button', { name: 'Deaccession' }))
    expect(await within(dialog).findByText(/A shipment of this strain waits for its second person/)).toBeInTheDocument()
  })

  it('a viewer sees the proposal and how the strain left, and no action', async () => {
    await render({ ...regulated, deaccession_proposal: PROPOSAL }, { canManage: false })
    const proposed = await screen.findByRole('region', { name: 'Proposed deaccession' })
    expect(within(proposed).queryByRole('button')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Actions for MYC 42' })).not.toBeInTheDocument()
  })
})
