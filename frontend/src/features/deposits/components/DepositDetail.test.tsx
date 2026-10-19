import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeDeposit, makeLab, makeMe, makeMtaTemplate, makeTaxon, makeTerms, page, problem } from '@/test/factories'
import { holdApi, mockApi, mockApiError } from '@/test/mockApi'
import { renderApp } from '@/test/render'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const DEPOSIT_ID = '00000000-0000-4000-8000-0000000000e1'
const DETAIL = '/api/v1/labs/{lab_public_id}/deposits/{public_id}/'
const ACTION = (name: 'start-check' | 'accept' | 'reject' | 'terms') => `/api/v1/labs/{lab_public_id}/deposits/{public_id}/${name}/` as const
// Invented taxa and people: test data states no real facts.
const exempli = makeTaxon({ public_id: '00000000-0000-4000-8000-0000000000c1', name: 'Testella exempli' })

function signedIn(role: 'viewer' | 'curator' = 'curator') {
  mockApi('get', '/api/v1/auth/me/', makeMe())
  mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: role }))
  mockApi('get', '/api/v1/labs/{lab_public_id}/mta-templates/', page([makeMtaTemplate()]))
  mockApi('get', '/api/v1/taxa/', page([exempli]))
}

const deposit = (overrides = {}) => makeDeposit({ public_id: DEPOSIT_ID, name_as_received: 'Testella exempli K3', ...overrides })
const open = () => renderApp({ path: `/labs/${LAB_ID}/deposits/${DEPOSIT_ID}` })

describe('the deposit page', { timeout: 20_000 }, () => {
  it('shows the receipt, the active terms and the steps, the check open', async () => {
    signedIn()
    mockApi('get', DETAIL, deposit({ condition: 'damaged', condition_note: 'cracked ampoule', depositor_passages: 3 }))
    open()
    expect(await screen.findByRole('heading', { level: 1, name: 'Deposit Testella exempli K3' }, { timeout: 5000 })).toBeInTheDocument()
    await waitFor(() => expect(document.title).toBe('Deposit Testella exempli K3 | Culture collection'))
    const steps = screen.getByRole('list', { name: 'Intake steps' })
    expect(within(steps).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['Received on 2026-10-01 (done)', 'Check started (now)', 'Accept or reject (to come)'])
    expect(screen.getByText('cracked ampoule')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Terms, version 1' })).toBeInTheDocument()
    expect(within(screen.getByRole('table', { name: 'Uses' })).getAllByRole('row')).toHaveLength(9)
    expect(screen.getByRole('button', { name: 'Start checking' })).toBeInTheDocument()
  })

  it('starts the check and moves the focus to the section, as the button goes', async () => {
    signedIn()
    mockApi('get', DETAIL, deposit())
    const calls = mockApi('post', ACTION('start-check'), deposit({ status: 'checking' }))
    open()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Start checking' }, { timeout: 5000 }))
    expect(await screen.findByRole('form', { name: 'Accept the deposit' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Check and decision' })).toHaveFocus()
    expect(calls[0]?.headers.get('X-CSRFToken')).toBe('test-token')
  })

  it('says so when someone else moved the deposit first', async () => {
    signedIn()
    mockApi('get', DETAIL, deposit())
    mockApiError('post', ACTION('start-check'), 409, problem(409, { code: 'deposit_state' }))
    open()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Start checking' }, { timeout: 5000 }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The deposit changed meanwhile. Reload the page.')
  })

  it('accepts with the facts and links the new strain, the focus on the section', async () => {
    signedIn()
    mockApi('get', DETAIL, deposit({ status: 'checking', terms: makeTerms({ country_of_origin: 'CZ' }) }))
    const accepted = deposit({ status: 'accepted', strain: { public_id: '00000000-0000-4000-8000-0000000000f1', accession_number: 'MYC 9' }, decided_at: '2026-10-02T10:00:00Z' })
    const calls = mockApi('post', ACTION('accept'), accepted)
    open()
    const user = userEvent.setup()
    const form = await screen.findByRole('form', { name: 'Accept the deposit' }, { timeout: 5000 })
    expect(within(form).getByText('Testella exempli K3')).toBeInTheDocument()
    expect(within(form).getByRole('combobox', { name: 'Country of origin' })).toHaveValue('CZ')
    await user.click(within(form).getByRole('combobox', { name: 'Taxon' }))
    await user.keyboard('exem')
    await screen.findByRole('option', { name: /Testella exempli/ }, { timeout: 4000 })
    await user.keyboard('{ArrowDown}{Enter}')
    await user.type(within(form).getByRole('textbox', { name: 'Identification method' }), '16S rRNA gene sequence')
    await user.selectOptions(within(form).getByRole('combobox', { name: 'Risk group' }), '2')
    await user.click(within(form).getByRole('button', { name: 'Accept and add the strain' }))
    const link = await screen.findByRole('link', { name: 'MYC 9' })
    expect(link).toHaveAttribute('href', `/labs/${LAB_ID}/strains/00000000-0000-4000-8000-0000000000f1`)
    expect(screen.getByRole('heading', { level: 2, name: 'Check and decision' })).toHaveFocus()
    expect(calls[0]?.body).toMatchObject({ taxon: exempli.public_id, risk_group: 2, country_of_origin: 'CZ' })
    expect(calls[0]?.body).not.toHaveProperty('name_as_received')
  })

  it('rejects with a reason in an alertdialog that opens on Cancel', async () => {
    signedIn()
    mockApi('get', DETAIL, deposit({ status: 'checking' }))
    const calls = mockApi('post', ACTION('reject'), deposit({ status: 'rejected', rejection_reason: 'Mixed culture.', decided_at: '2026-10-02T10:00:00Z' }))
    open()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Reject the deposit' }, { timeout: 5000 }))
    const dialog = await screen.findByRole('alertdialog', { name: 'Reject Testella exempli K3?' })
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus()
    await user.click(within(dialog).getByRole('button', { name: 'Reject the deposit' }))
    expect(within(dialog).getByRole('textbox', { name: 'Reason' })).toHaveAccessibleDescription(/Say why$/)
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'Mixed culture.')
    await user.click(within(dialog).getByRole('button', { name: 'Reject the deposit' }))
    expect(await screen.findByText(/^Rejected on .*: Mixed culture\.$/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('heading', { level: 2, name: 'Check and decision' })).toHaveFocus())
    expect(calls[0]?.body).toEqual({ reason: 'Mixed culture.' })
  })

  it('changes the terms from the current version, with a reason, and keeps the dialog open while it saves', async () => {
    signedIn()
    mockApi('get', DETAIL, deposit({ status: 'checking' }))
    const held = holdApi('post', ACTION('terms'))
    open()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Change the terms' }, { timeout: 5000 }))
    const dialog = await screen.findByRole('dialog', { name: 'Change the terms' })
    expect(dialog).toHaveAccessibleDescription(/adds version 2/)
    expect(within(dialog).getByRole('combobox', { name: 'Teaching' })).toHaveValue('permit')
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Teaching' }), 'deny')
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'The depositor withdrew teaching.')
    const save = within(dialog).getByRole('button', { name: 'Save the new version' })
    await user.click(save)
    await waitFor(() => expect(save).toHaveAttribute('aria-disabled', 'true'))
    await user.keyboard('{Escape}')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(held.calls[0]?.body).toMatchObject({ reason: 'The depositor withdrew teaching.', terms: { abs_scope: 'not_in_scope', mta: null } })
    held.release(200, deposit({ status: 'checking', terms: makeTerms({ version: 2 }) }))
    expect(await screen.findByRole('heading', { level: 2, name: 'Terms, version 2' })).toBeInTheDocument()
  })

  it.each([
    ['accepted', () => deposit({ status: 'accepted', strain: { public_id: '00000000-0000-4000-8000-0000000000f1', accession_number: 'MYC 9' }, decided_at: '2026-10-02T10:00:00Z' })],
    ['rejected', () => deposit({ status: 'rejected', rejection_reason: 'Mixed.', decided_at: '2026-10-02T10:00:00Z' })],
  ])('offers no action on a %s deposit but the terms of an accepted one', async (status, make) => {
    signedIn()
    mockApi('get', DETAIL, make())
    open()
    await screen.findByRole('heading', { level: 1 }, { timeout: 5000 })
    expect(screen.queryByRole('button', { name: 'Start checking' })).not.toBeInTheDocument()
    expect(screen.queryByRole('form', { name: 'Accept the deposit' })).not.toBeInTheDocument()
    expect(screen.queryAllByRole('button', { name: 'Change the terms' })).toHaveLength(status === 'accepted' ? 1 : 0)
  })

  it('has a title in its not-found and error states, and tells a viewer that deposits are for curators', async () => {
    allowConsole(/API error 500/)
    signedIn()
    mockApiError('get', DETAIL, 404, problem(404))
    open()
    expect(await screen.findByRole('heading', { level: 1, name: 'Deposit not found' }, { timeout: 5000 })).toBeInTheDocument()
  })

  it('tells a viewer that deposits are for curators, without loading the deposit into the page', async () => {
    signedIn('viewer')
    mockApiError('get', DETAIL, 403, problem(403))
    open()
    expect(await screen.findByText(/Only curators and managers see deposits/, undefined, { timeout: 5000 })).toBeInTheDocument()
  })
})
