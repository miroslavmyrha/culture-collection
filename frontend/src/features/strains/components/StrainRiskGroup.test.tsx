import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeStrain, makeTerms, problem } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { StrainOverview } from './StrainOverview'
import { StrainShell } from './StrainShell'

// A risk group drops by two people (#174, ADR 0009): a curator or manager proposes the lower
// group with the basis it rests on, a manager other than the proposer confirms it. A raise is
// one person's and goes one step at a time. Invented strain, so no real organism is shown with
// a group it does not have.

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const STRAIN_ID = '00000000-0000-4000-8000-0000000000d1'
const DETAIL = '/api/v1/labs/{lab_public_id}/strains/{public_id}/'
const TERMS = '/api/v1/labs/{lab_public_id}/strains/{public_id}/terms/'
const CHANGE = '/api/v1/labs/{lab_public_id}/strains/{public_id}/risk-group/'
const PROPOSE = '/api/v1/labs/{lab_public_id}/strains/{public_id}/risk-group-proposal/'
const CONFIRM = '/api/v1/labs/{lab_public_id}/strains/{public_id}/risk-group-proposal/confirm/'
const WITHDRAW = '/api/v1/labs/{lab_public_id}/strains/{public_id}/risk-group-proposal/withdraw/'

const BASIS = 'NV 361/2007 Sb., Příloha 7: the agent is in none of the groups 2 to 4.'
const group2 = makeStrain({ public_id: STRAIN_ID, accession_number: 'MYC 42', risk_group: 2 })
const PROPOSAL = {
  public_id: '00000000-0000-4000-8000-0000000000f1',
  risk_group: 1 as const,
  from_risk_group: 2 as const,
  basis: BASIS,
  // #169: this basis rests on no entry of annex 7, only on the words.
  basis_entry: null,
  reason: 'Reassessed against the annex.',
  proposed_at: '2026-11-03T10:00:00Z',
  confirm_refusal: null,
}
const lowered = { ...group2, risk_group: 1 as const, risk_group_basis: BASIS, risk_group_proposal: null }

function render(strain: typeof group2, { canManage = true, canConfirmRisk = false } = {}) {
  mockApi('get', DETAIL, strain)
  mockApi('get', TERMS, { deposit: null, versions: [makeTerms()] })
  return renderWithProviders(
    <main>
      <StrainShell labId={LAB_ID} strainId={STRAIN_ID} canManage={canManage}>
        {(s) => <StrainOverview labId={LAB_ID} strain={s} canManage={canManage} canConfirm={false} canConfirmRisk={canConfirmRisk} />}
      </StrainShell>
    </main>,
  )
}

async function dialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: 'Actions for MYC 42' }))
  await user.click(await screen.findByRole('menuitem', { name: 'Change risk group' }))
  return screen.findByRole('dialog', { name: 'Change the risk group of MYC 42' })
}

describe('the risk group on the strain page', () => {
  it('raises the group in one step, with its basis', async () => {
    const raise = mockApi('post', CHANGE, { ...group2, risk_group: 3, risk_group_basis: BASIS })
    const proposals = mockApi('post', PROPOSE, group2)
    await render(group2)
    const user = userEvent.setup()
    const open = await dialog(user)
    expect(open).toHaveAccessibleDescription(/A higher group takes effect at once and rises one step at a time/)
    await user.selectOptions(within(open).getByRole('combobox', { name: 'Risk group' }), '3')
    await user.type(within(open).getByRole('textbox', { name: 'Basis' }), `  ${BASIS} `)
    await user.type(within(open).getByRole('textbox', { name: 'Reason' }), 'Reassessed.')
    await user.click(within(open).getByRole('button', { name: 'Save risk group' }))
    await waitFor(() => expect(open).not.toBeInTheDocument())
    expect(raise[0]?.body).toEqual({ risk_group: 3, basis: BASIS, basis_entry: null, reason: 'Reassessed.' })
    expect(proposals).toHaveLength(0)
  })

  it('turns a lower group into a proposal and says a manager confirms it', async () => {
    const change = mockApi('post', CHANGE, group2)
    const propose = mockApi('post', PROPOSE, {
      ...group2,
      risk_group_proposal: { ...PROPOSAL, confirm_refusal: 'confirm_own_risk_group' as const },
    })
    await render(group2)
    const user = userEvent.setup()
    const open = await dialog(user)
    await user.selectOptions(within(open).getByRole('combobox', { name: 'Risk group' }), '1')
    await waitFor(() => expect(open).toHaveAccessibleDescription(/A lower risk group waits for a manager other than you to confirm it/))
    await user.type(within(open).getByRole('textbox', { name: 'Basis' }), BASIS)
    await user.type(within(open).getByRole('textbox', { name: 'Reason' }), 'Reassessed against the annex.')
    await user.click(within(open).getByRole('button', { name: 'Propose the lower group' }))
    await waitFor(() => expect(open).not.toBeInTheDocument())
    expect(propose[0]?.body).toEqual({ risk_group: 1, basis: BASIS, basis_entry: null, reason: 'Reassessed against the annex.' })
    expect(change).toHaveLength(0)
    // The strain keeps its group, and the page says who settles the proposal.
    expect(within(screen.getByRole('list', { name: 'Biosafety and status' })).getByText('Risk group 2')).toBeInTheDocument()
    const proposed = screen.getByRole('region', { name: 'Proposed risk group' })
    expect(proposed).toHaveTextContent('New risk group1, down from 2')
    expect(within(proposed).getByText('You proposed it: a different manager confirms.')).toBeInTheDocument()
    expect(within(proposed).queryByRole('button', { name: 'Confirm the lower risk group' })).not.toBeInTheDocument()
  })

  it('says inside the dialog that a raise goes one step at a time', async () => {
    allowConsole(/API error 400/)
    mockApiError('post', CHANGE, 400, {
      ...problem(400, { code: 'risk_group_step_too_big' }),
      errors: [{ attr: 'risk_group', code: 'risk_group_step_too_big', detail: 'server words' }],
    })
    await render(makeStrain({ public_id: STRAIN_ID, accession_number: 'MYC 42', risk_group: 1 }))
    const user = userEvent.setup()
    const open = await dialog(user)
    const group = within(open).getByRole('combobox', { name: 'Risk group' })
    await user.selectOptions(group, '3')
    await user.type(within(open).getByRole('textbox', { name: 'Basis' }), BASIS)
    await user.type(within(open).getByRole('textbox', { name: 'Reason' }), 'Reassessed.')
    await user.click(within(open).getByRole('button', { name: 'Save risk group' }))
    await waitFor(() => expect(group).toHaveAccessibleDescription(/rises one step at a time: raise it by one, with its basis, then again\.$/))
    expect(group).toHaveFocus()
    expect(open).not.toHaveTextContent('server words')
  })

  it('another manager confirms the proposal they read', async () => {
    const calls = mockApi('post', CONFIRM, lowered)
    await render({ ...group2, risk_group_proposal: PROPOSAL }, { canConfirmRisk: true })
    const user = userEvent.setup()
    const proposed = await screen.findByRole('region', { name: 'Proposed risk group' })
    expect(within(proposed).getByText('Waiting for your confirmation.')).toBeInTheDocument()
    await user.click(within(proposed).getByRole('button', { name: 'Confirm the lower risk group' }))
    const open = await screen.findByRole('alertdialog', { name: 'Lower the risk group to 1?' })
    expect(within(open).getByText(`Basis given: ${BASIS}`)).toBeInTheDocument()
    expect(within(open).getByText('Reason given: Reassessed against the annex.')).toBeInTheDocument()
    await user.click(within(open).getByRole('button', { name: 'Lower the risk group' }))
    await waitFor(() => expect(open).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ proposal: PROPOSAL.public_id })
    expect(within(screen.getByRole('list', { name: 'Biosafety and status' })).getByText('Risk group 1')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Proposed risk group' })).not.toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Facts' })).toHaveTextContent(`Basis of the risk group${BASIS}`)
  })

  it('does not offer the confirmation to the manager who proposed it', async () => {
    await render(
      { ...group2, risk_group_proposal: { ...PROPOSAL, confirm_refusal: 'confirm_own_risk_group' as const } },
      { canConfirmRisk: true },
    )
    const proposed = await screen.findByRole('region', { name: 'Proposed risk group' })
    expect(within(proposed).getByText('You proposed it: a different manager confirms.')).toBeInTheDocument()
    expect(within(proposed).queryByRole('button', { name: 'Confirm the lower risk group' })).not.toBeInTheDocument()
    expect(within(proposed).getByRole('button', { name: 'Withdraw the proposal' })).toBeInTheDocument()
  })

  it('a curator sees who confirms and may withdraw the proposal with a reason', async () => {
    const calls = mockApi('post', WITHDRAW, group2)
    await render({ ...group2, risk_group_proposal: PROPOSAL })
    const user = userEvent.setup()
    const proposed = await screen.findByRole('region', { name: 'Proposed risk group' })
    expect(within(proposed).getByText('Waiting for a manager to confirm.')).toBeInTheDocument()
    expect(within(proposed).queryByRole('button', { name: 'Confirm the lower risk group' })).not.toBeInTheDocument()
    await user.click(within(proposed).getByRole('button', { name: 'Withdraw the proposal' }))
    const open = await screen.findByRole('dialog', { name: 'Withdraw the proposal to lower the risk group of MYC 42' })
    await user.type(within(open).getByRole('textbox', { name: 'Reason' }), 'The annex lists it after all.')
    await user.click(within(open).getByRole('button', { name: 'Withdraw' }))
    await waitFor(() => expect(open).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ proposal: PROPOSAL.public_id, reason: 'The annex lists it after all.' })
    expect(screen.queryByRole('region', { name: 'Proposed risk group' })).not.toBeInTheDocument()
    // The button that opened the dialog is gone with its section: focus goes to the page's h1.
    await waitFor(() => expect(screen.getByRole('heading', { level: 1, name: 'MYC 42' })).toHaveFocus())
  })

  it('says inside the dialog why the confirmation was refused', async () => {
    allowConsole(/API error 409/)
    mockApiError('post', CONFIRM, 409, problem(409, { code: 'risk_group_proposal_outdated' }))
    await render({ ...group2, risk_group_proposal: PROPOSAL }, { canConfirmRisk: true })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Confirm the lower risk group' }))
    const open = await screen.findByRole('alertdialog', { name: 'Lower the risk group to 1?' })
    await user.click(within(open).getByRole('button', { name: 'Lower the risk group' }))
    expect(await within(open).findByText(/risk group changed since the proposal/)).toBeInTheDocument()
  })

  it('a viewer and a technician see the proposal and no action', async () => {
    await render({ ...group2, risk_group_proposal: PROPOSAL }, { canManage: false })
    const proposed = await screen.findByRole('region', { name: 'Proposed risk group' })
    expect(proposed).toHaveTextContent(`Basis${BASIS}`)
    expect(within(proposed).getByText('Waiting for a manager to confirm.')).toBeInTheDocument()
    expect(within(proposed).queryByRole('button')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Actions for MYC 42' })).not.toBeInTheDocument()
  })

  it('shows where the current group comes from, with the annex entry it cites', async () => {
    await render({ ...group2, risk_group_basis: BASIS, risk_group_entry: '1.99' })
    expect(await screen.findByRole('region', { name: 'Facts' })).toHaveTextContent(`Basis of the risk group${BASIS} (annex 7, entry 1.99)`)
  })

  it('says a group from an accession before the basis was asked for comes from the accession', async () => {
    await render({ ...group2, risk_group_basis: '', risk_group_entry: null })
    expect(await screen.findByRole('region', { name: 'Facts' })).toHaveTextContent('Basis of the risk groupFrom the accession')
  })
})
