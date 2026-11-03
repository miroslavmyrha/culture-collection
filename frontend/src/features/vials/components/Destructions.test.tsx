import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { makeDestruction, makeMember, makeVial, page, problem } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { Destructions } from './Destructions'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const STRAIN_ID = '00000000-0000-4000-8000-0000000000d1'
const DESTRUCTIONS = '/api/v1/labs/{lab_public_id}/destructions/'
const VIALS = '/api/v1/labs/{lab_public_id}/vials/'
const MEMBERS = '/api/v1/labs/{lab_public_id}/members/'
const CONFIRM = '/api/v1/labs/{lab_public_id}/destructions/{public_id}/confirm/'
const IN_ERROR = '/api/v1/labs/{lab_public_id}/destructions/{public_id}/enter-in-error/'

const first = makeVial({ label: 'MYC 42 / 1 / 1', status: 'to_destroy', status_changed_at: '2026-10-02T10:00:00Z' })
const second = makeVial({ label: 'MYC 42 / 1 / 2', status: 'to_destroy', status_changed_at: '2026-10-02T10:00:00Z' })
const tech = makeMember({ username: 'tech', role: 'technician' })
const other = makeMember({ username: 'witness', first_name: 'Wanda', last_name: 'Wit', role: 'technician' })
const viewer = makeMember({ username: 'viewer', role: 'viewer' })

type Options = { kinds?: readonly string[]; canHandle?: boolean; canConfirm?: boolean }

function render({ kinds = [], canHandle = true, canConfirm = false }: Options = {}) {
  return renderWithProviders(<Destructions labId={LAB_ID} strainId={STRAIN_ID} accession="MYC 42" kinds={kinds} canHandle={canHandle} canConfirm={canConfirm} />)
}

async function openRecord() {
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Record a destruction' }))
  const dialog = await screen.findByRole('dialog', { name: 'Record a destruction' })
  await within(dialog).findByRole('group', { name: 'Vials destroyed' })
  return { user, dialog }
}

/** Every field the form shows, by its accessible name, in order. */
const fieldNames = (dialog: HTMLElement) =>
  [...dialog.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>('input, select, textarea')]
    .filter((field) => field.type !== 'hidden' && !field.hidden && field.getAttribute('aria-hidden') !== 'true')
    .map((field) => field.labels?.[0]?.textContent?.replace(/\s*\*$/, '') ?? '')

describe('the destruction record (#160)', () => {
  it('lists the records with where each stands, and nothing to change for a viewer', async () => {
    mockApi('get', DESTRUCTIONS, page([
      makeDestruction({ number: '2026/2', awaits_confirmation: true, completed_at: null, recorded_by: 'tech', witness: 'witness' }),
      makeDestruction({ number: '2026/1', confirmed_by: 'boss', confirmed_at: '2026-10-05T10:00:00Z', contractor: 'Spalovna s.r.o.', handover_document: 'PP-7' }),
      makeDestruction({ number: '2025/9', status: 'entered_in_error', error_reason: 'Wrong vials.', entered_in_error_by: 'tech' }),
    ]))
    await render({ canHandle: false })
    const table = await screen.findByRole('table', { name: 'Destruction records' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows[0]).toHaveTextContent('Waits for a manager other than tech to confirm')
    expect(rows[0]).toHaveTextContent('Witness: witness')
    expect(rows[1]).toHaveTextContent('Destroyed. Recorded by tech, confirmed by boss')
    expect(rows[1]).toHaveTextContent('Handed to Spalovna s.r.o., document PP-7, inactivated in the lab first')
    expect(rows[2]).toHaveTextContent('Entered in error by tech: Wrong vials.')
    expect(screen.queryByRole('button', { name: /Record a destruction|Confirm|in error/ })).not.toBeInTheDocument()
  })

  it.each([
    ['without restrictions', [], ['Destroyed on', 'Method', 'Method details', 'Verification of the inactivation', 'Handed to an outside firm', 'Run', 'Reason'], 'Record and destroy'],
    ['regulated (dual-use)', ['dual_use'], ['Destroyed on', 'Method', 'Method details', 'Verification of the inactivation', 'Handed to an outside firm', 'Run', 'Reason'], 'Record for confirmation'],
    ['a VRAT', ['cz_vrat'], ['Destroyed on', 'Method', 'Method details', 'Verification of the inactivation', 'Witness', 'Handed to an outside firm', 'Run', 'Reason'], 'Record for confirmation'],
  ])('asks a strain %s for its fields', async (_case, kinds, fields, confirm) => {
    mockApi('get', DESTRUCTIONS, page([]))
    mockApi('get', VIALS, page([first, second]))
    mockApi('get', MEMBERS, page([tech, other, viewer]))
    await render({ kinds })
    const { dialog } = await openRecord()
    if (kinds.includes('cz_vrat')) await within(dialog).findByRole('combobox', { name: 'Witness' })
    const names = fieldNames(dialog).filter((name) => !name.startsWith('MYC 42'))
    expect(names).toEqual(fields)
    expect(within(dialog).getByRole('checkbox', { name: 'MYC 42 / 1 / 1' })).toBeChecked()
    expect(within(dialog).getByRole('button', { name: confirm })).toBeInTheDocument()
  })

  it('records the destruction of a strain without restrictions with what was chosen', async () => {
    mockApi('get', DESTRUCTIONS, page([]))
    mockApi('get', VIALS, page([first, second]))
    const calls = mockApi('post', DESTRUCTIONS, makeDestruction())
    await render()
    const { user, dialog } = await openRecord()
    await user.click(within(dialog).getByRole('checkbox', { name: 'MYC 42 / 1 / 2' }))
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'Contaminated.')
    await user.click(within(dialog).getByRole('button', { name: 'Record and destroy' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toMatchObject({
      strain: STRAIN_ID,
      vials: [first.public_id],
      method: 'autoclave',
      verification: '',
      contractor: '',
      handover_document: '',
      inactivated_in_lab: true,
      witness: null,
      reason: 'Contaminated.',
    })
  })

  it('asks a VRAT for its verification and witness, and refuses it alive to a firm, before sending', async () => {
    mockApi('get', DESTRUCTIONS, page([]))
    mockApi('get', VIALS, page([first]))
    mockApi('get', MEMBERS, page([tech, other, viewer]))
    const calls = mockApi('post', DESTRUCTIONS, makeDestruction({ awaits_confirmation: true, completed_at: null }))
    await render({ kinds: ['cz_vrat'] })
    const { user, dialog } = await openRecord()
    const witness = await within(dialog).findByRole('combobox', { name: 'Witness' })
    // Only members who handle vials witness.
    expect(within(witness).getAllByRole('option').map((o) => o.textContent)).toEqual(['Choose a member', 'tech', 'witness (Wanda Wit)'])
    await user.click(within(dialog).getByRole('checkbox', { name: 'Handed to an outside firm' }))
    await user.click(within(dialog).getByRole('checkbox', { name: 'Inactivated in the lab before the handover' }))
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'Activity ended.')
    await user.click(within(dialog).getByRole('button', { name: 'Record for confirmation' }))
    expect(within(dialog).getByRole('textbox', { name: 'Verification of the inactivation' })).toHaveAccessibleDescription(/Say how the inactivation was verified/)
    expect(witness).toHaveAccessibleDescription(/Choose the member who witnessed it/)
    expect(within(dialog).getByText('A highly risky or risky agent (VRAT, RAT) is inactivated in the lab before a firm takes it')).toBeInTheDocument()
    expect(calls).toHaveLength(0)
    await user.type(within(dialog).getByRole('textbox', { name: 'Verification of the inactivation' }), 'Spore strip: no growth.')
    await user.selectOptions(witness, other.public_id)
    await user.click(within(dialog).getByRole('checkbox', { name: 'Inactivated in the lab before the handover' }))
    await user.type(within(dialog).getByRole('textbox', { name: 'Firm' }), 'Spalovna s.r.o., IČO 12345678')
    await user.type(within(dialog).getByRole('textbox', { name: 'Handover document' }), 'PP-7')
    await user.click(within(dialog).getByRole('button', { name: 'Record for confirmation' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toMatchObject({
      verification: 'Spore strip: no growth.',
      witness: other.public_id,
      contractor: 'Spalovna s.r.o., IČO 12345678',
      handover_document: 'PP-7',
      inactivated_in_lab: true,
    })
  })

  it("names the server's refusal of a quarantine pest's method on the method field", async () => {
    mockApi('get', DESTRUCTIONS, page([]))
    mockApi('get', VIALS, page([first]))
    mockApiError('post', DESTRUCTIONS, 400, problem(400, { code: 'invalid', errors: [{ attr: 'method', code: 'method_not_authorised', detail: "The lab's ÚKZÚZ permit P-1 declares autoclaving." }] }))
    await render({ kinds: ['quarantine_pest'] })
    const { user, dialog } = await openRecord()
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Method' }), 'incineration')
    await user.type(within(dialog).getByRole('textbox', { name: 'Verification of the inactivation' }), 'Ash only.')
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'Activity ended.')
    await user.click(within(dialog).getByRole('button', { name: 'Record for confirmation' }))
    await waitFor(() => expect(within(dialog).getByRole('combobox', { name: 'Method' })).toHaveAccessibleDescription(/declares autoclaving/))
    expect(within(dialog).getByRole('combobox', { name: 'Method' })).toHaveFocus()
  })

  it("names the server's refusal of a witness without VRAT access on the witness field (#167)", async () => {
    mockApi('get', DESTRUCTIONS, page([]))
    mockApi('get', VIALS, page([first]))
    mockApi('get', MEMBERS, page([tech, other, viewer]))
    mockApiError(
      'post',
      DESTRUCTIONS,
      400,
      problem(400, {
        code: 'invalid',
        errors: [{ attr: 'witness', code: 'witness_without_vrat_access', detail: 'Not on the list.' }],
      }),
    )
    await render({ kinds: ['cz_vrat'] })
    const { user, dialog } = await openRecord()
    const witness = await within(dialog).findByRole('combobox', { name: 'Witness' })
    // The form says the rule before anything is sent: the access list is a manager's to read.
    expect(witness).toHaveAccessibleDescription(/on the lab's VRAT access list on that day/)
    await user.selectOptions(witness, other.public_id)
    await user.type(within(dialog).getByRole('textbox', { name: 'Verification of the inactivation' }), 'Spore strip: no growth.')
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'Activity ended.')
    await user.click(within(dialog).getByRole('button', { name: 'Record for confirmation' }))
    await waitFor(() => expect(witness).toHaveAccessibleDescription(/Not on the list\./))
    expect(witness).toHaveFocus()
  })

  it('leaves vials of a record that waits for its confirmation out of a new one', async () => {
    mockApi('get', DESTRUCTIONS, page([makeDestruction({ awaits_confirmation: true, completed_at: null, vials: [{ public_id: first.public_id, label: first.label }] })]))
    mockApi('get', VIALS, page([first, second]))
    await render({ kinds: ['dual_use'] })
    const { dialog } = await openRecord()
    expect(within(dialog).queryByRole('checkbox', { name: 'MYC 42 / 1 / 1' })).not.toBeInTheDocument()
    expect(within(dialog).getByRole('checkbox', { name: 'MYC 42 / 1 / 2' })).toBeChecked()
  })

  it('lets a manager confirm a waiting record, and names the refusal of the recorder', async () => {
    const waiting = makeDestruction({ number: '2026/3', awaits_confirmation: true, completed_at: null, recorded_by: 'boss' })
    mockApi('get', DESTRUCTIONS, page([waiting]))
    mockApiError('post', CONFIRM, 403, problem(403, { code: 'confirm_own_destruction' }))
    await render({ kinds: ['cz_rat'], canConfirm: true })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Confirm destruction 2026/3' }))
    const dialog = await screen.findByRole('alertdialog', { name: 'Confirm destruction 2026/3?' })
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus()
    expect(dialog).toHaveAccessibleDescription(/Confirmed, the vials are destroyed and leave their boxes\. This cannot be undone\./)
    await user.click(within(dialog).getByRole('button', { name: 'Confirm destruction' }))
    expect(await within(dialog).findByText('You recorded this destruction: a different manager confirms it.')).toBeInTheDocument()
  })

  it('offers no confirmation to a curator, and enters a waiting record in error with a reason', async () => {
    const waiting = makeDestruction({ number: '2026/3', awaits_confirmation: true, completed_at: null })
    mockApi('get', DESTRUCTIONS, page([waiting]))
    const calls = mockApi('post', IN_ERROR, { ...waiting, status: 'entered_in_error' })
    await render({ kinds: ['cz_rat'] })
    const user = userEvent.setup()
    await screen.findByRole('table', { name: 'Destruction records' })
    expect(screen.queryByRole('button', { name: /^Confirm/ })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Enter destruction 2026/3 in error' }))
    const dialog = await screen.findByRole('alertdialog', { name: 'Enter destruction 2026/3 in error?' })
    expect(dialog).toHaveAccessibleDescription(/Its vials stay marked to destroy, for a new record/)
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'Wrong vials.')
    await user.click(within(dialog).getByRole('button', { name: 'Enter in error' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ reason: 'Wrong vials.' })
  })

  it('leaves a confirmed record to a manager to enter in error', async () => {
    mockApi('get', DESTRUCTIONS, page([makeDestruction({ number: '2026/4', confirmed_by: 'boss', confirmed_at: '2026-10-05T10:00:00Z' })]))
    await render({ kinds: ['cz_rat'] })
    await screen.findByRole('table', { name: 'Destruction records' })
    expect(screen.queryByRole('button', { name: 'Enter destruction 2026/4 in error' })).not.toBeInTheDocument()
  })
})
