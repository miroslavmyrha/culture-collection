import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { allowConsole } from '@/test/console'
import { makeAcceptance, makeFinding, makeLab, makeMe, makePreparation, makeRequest, makeRequestLine, makeShipment, makeShipmentDocument, makeVial, problem, validationProblem } from '@/test/factories'
import { holdApi, mockApi, mockApiError } from '@/test/mockApi'
import { renderApp } from '@/test/render'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const REQUEST_ID = '00000000-0000-4000-8000-0000000000a1'
const DETAIL = '/api/v1/labs/{lab_public_id}/requests/{public_id}/'
const VIALS = '/api/v1/labs/{lab_public_id}/requests/{public_id}/vials/'
const ACTION = (name: 'approve' | 'reject' | 'cancel' | 'ship' | 'prepare-shipment' | 'confirm-shipment' | 'withdraw-shipment') => `/api/v1/labs/{lab_public_id}/requests/{public_id}/${name}/` as const

function signedIn(role: 'viewer' | 'technician' | 'curator' | 'manager' = 'curator') {
  mockApi('get', '/api/v1/auth/me/', makeMe())
  mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: role }))
}

const line = makeRequestLine({ public_id: '00000000-0000-4000-8000-0000000000b1', strain: { public_id: '00000000-0000-4000-8000-0000000000c1', accession_number: 'MYC 3', taxon: 'Mockia vulgaris', risk_group: 2 } })
const request = (overrides = {}) => makeRequest({ public_id: REQUEST_ID, number: '2026/7', lines: [line], ...overrides })
const open = () => renderApp({ path: `/labs/${LAB_ID}/requests/${REQUEST_ID}` })
const blocked = [makeFinding({ code: 'loa_missing', sentence: 'MYC 3 is a quarantine pest: the requester shows no valid Letter of Authority that names Mockia vulgaris.', line: line.public_id })]
const regulated = [makeFinding({ code: 'regulated', severity: 'manager', sentence: 'MYC 3 is regulated (dual_use): a manager approves it.', line: line.public_id })]
const preparation = (overrides = {}) => makePreparation({ public_id: '00000000-0000-4000-8000-0000000000f1', prepared_at: '2026-10-21T08:00:00Z', ...overrides })

async function openShipDialog() {
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Ship the vials' }, { timeout: 5000 }))
  return { user, dialog: await screen.findByRole('dialog', { name: 'Ship request 2026/7?' }) }
}

async function fillPerson(user: ReturnType<typeof userEvent.setup>, dialog: HTMLElement) {
  await user.type(within(dialog).getByRole('textbox', { name: 'Responsible person' }), 'Jan Odpovědný')
  await user.type(within(dialog).getByRole('textbox', { name: 'Phone of the responsible person' }), '+420 555 000 111')
  await user.type(within(dialog).getByRole('textbox', { name: 'Carrier' }), 'Example Courier')
}

/** A request in `status` opened by a technician; answers the requests for its vials to pull. */
function reservedOn(status: 'approved' | 'awaiting_confirmation' | 'submitted' | 'shipped' | 'cancelled') {
  signedIn('technician')
  const asked = mockApi('get', VIALS, [makeVial({ label: 'MYC 3 / 1 / 1', status: 'reserved', placed: true, location_masked: true })])
  mockApi('get', DETAIL, request({ status, decided_by: 'curator', decided_at: '2026-10-20T10:00:00Z', preparations: status === 'awaiting_confirmation' ? [preparation()] : [] }))
  open()
  return asked
}

// While vials are reserved the page lists where they lie (#143): none, unless a test says.
beforeEach(() => {
  mockApi('get', VIALS, [])
})

describe('the request page', { timeout: 20_000 }, () => {
  it('shows what is asked, the strains with their pinned terms and the findings by severity', async () => {
    signedIn()
    mockApi('get', DETAIL, request({ findings: [...blocked, ...regulated] }))
    open()
    expect(await screen.findByRole('heading', { level: 1, name: 'Request 2026/7' }, { timeout: 5000 })).toBeInTheDocument()
    await waitFor(() => expect(document.title).toBe('Request 2026/7 | Culture collection'))
    const strains = screen.getByRole('table', { name: 'Strains' })
    expect(within(strains).getAllByRole('row')[1]).toHaveTextContent('MYC 3, Mockia vulgaris22Terms version 1, MTA STD version 1None')
    expect(within(screen.getByRole('list', { name: 'Blocks the approval' })).getByRole('listitem')).toHaveTextContent(/Letter of Authority/)
    expect(within(screen.getByRole('list', { name: 'Needs a manager’s approval' })).getByRole('listitem')).toHaveTextContent(/regulated/)
    expect(screen.queryByRole('button', { name: 'Approve and reserve the vials' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reject the request' })).toBeInTheDocument()
  })

  it('offers a curator no approval over a manager finding, and a manager approves with a reason', async () => {
    signedIn('curator')
    mockApi('get', DETAIL, request({ findings: regulated }))
    const { unmount } = open()
    expect(await screen.findByText('A manager approves this request.', {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve and reserve the vials' })).not.toBeInTheDocument()
    unmount()
    signedIn('manager')
    mockApi('get', DETAIL, request({ findings: regulated }))
    open()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Approve and reserve the vials' }, { timeout: 5000 }))
    const dialog = await screen.findByRole('dialog', { name: 'Approve request 2026/7?' })
    const calls = mockApi('post', ACTION('approve'), request({ status: 'approved', decided_by: 'manager', decision_reason: 'Inside the EU.' }))
    await user.click(within(dialog).getByRole('button', { name: 'Approve and reserve' }))
    expect(within(dialog).getByRole('textbox', { name: 'Reason' })).toHaveAccessibleDescription(/Say why the findings allow it/)
    expect(calls).toHaveLength(0)
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'Inside the EU.')
    await user.click(within(dialog).getByRole('button', { name: 'Approve and reserve' }))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]?.body).toEqual({ reason: 'Inside the EU.' })
    expect(await screen.findByText(/Approved by manager on .*: Inside the EU\./, {}, { timeout: 5000 })).toBeInTheDocument()
  })

  it('keeps the approval dialog open while it runs and says when the policy stopped it', async () => {
    signedIn('curator')
    mockApi('get', DETAIL, request())
    open()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Approve and reserve the vials' }, { timeout: 5000 }))
    const dialog = await screen.findByRole('dialog')
    const held = holdApi('post', ACTION('approve'))
    await user.click(within(dialog).getByRole('button', { name: 'Approve and reserve' }))
    await waitFor(() => expect(held.calls).toHaveLength(1))
    await user.keyboard('{Escape}')
    expect(dialog).toBeInTheDocument()
    allowConsole(/API error 422/)
    held.release(422, problem(422, { code: 'request_blocked', detail: 'MYC 3: 0 vials may go out now.' }))
    expect(await within(dialog).findByText('Something blocks the approval now. Close this and read what stands in the way.')).toBeInTheDocument()
  })

  it('rejects with a reason in an alertdialog that opens on Cancel', async () => {
    signedIn()
    mockApi('get', DETAIL, request())
    open()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Reject the request' }, { timeout: 5000 }))
    const dialog = await screen.findByRole('alertdialog', { name: 'Reject request 2026/7?' })
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus()
    const calls = mockApi('post', ACTION('reject'), request({ status: 'rejected', decided_by: 'curator', decision_reason: 'No laboratory.', decided_at: '2026-10-20T10:00:00Z' }))
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'No laboratory.')
    await user.click(within(dialog).getByRole('button', { name: 'Reject the request' }))
    await waitFor(() => expect(calls[0]?.body).toEqual({ reason: 'No laboratory.' }))
    expect(await screen.findByText('Rejected by curator on 2026-10-20: No laboratory.', {}, { timeout: 5000 })).toBeInTheDocument()
  })

  it('lists the reserved vials by label and lets a curator cancel, which frees them', async () => {
    signedIn()
    const reserved = makeRequestLine({ ...line, reserved: [{ public_id: '00000000-0000-4000-8000-0000000000e1', label: 'MYC 3 / 1 / 1' }] })
    mockApi('get', DETAIL, request({ status: 'approved', decided_by: 'curator', decided_at: '2026-10-20T10:00:00Z', lines: [reserved] }))
    open()
    expect(await screen.findByRole('cell', { name: 'MYC 3 / 1 / 1' }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByText(/Box|Freezer/)).not.toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Cancel the request' }))
    const dialog = await screen.findByRole('alertdialog', { name: 'Cancel request 2026/7?' })
    expect(dialog).toHaveAccessibleDescription(/its reserved vial is available again/)
  })

  it.each(['approved', 'awaiting_confirmation'] as const)('lists the vials to pull with their places while the request is %s', async (status) => {
    reservedOn(status)
    const section = await screen.findByRole('region', { name: 'Vials to pull' }, { timeout: 5000 })
    expect(await within(section).findByRole('row', { name: '1 MYC 3 / 1 / 1 Hidden: regulated strain' })).toBeInTheDocument()
  })

  it.each(['submitted', 'shipped', 'cancelled'] as const)('lists no vials to pull and asks for none while the request is %s', async (status) => {
    const asked = reservedOn(status)
    expect(await screen.findByRole('heading', { level: 1, name: 'Request 2026/7' }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Vials to pull' })).not.toBeInTheDocument()
    expect(asked).toHaveLength(0)
  })

  it('keeps one page title while the vials to pull load and when they fail', async () => {
    allowConsole(/API error 500/)
    signedIn('technician')
    mockApiError('get', VIALS, 500)
    mockApi('get', DETAIL, request({ status: 'approved', decided_by: 'curator', decided_at: '2026-10-20T10:00:00Z' }))
    open()
    expect(await screen.findByText(/Could not load the vials to pull/, {}, { timeout: 5000 })).toBeInTheDocument()
    expect(document.title).toBe('Request 2026/7 | Culture collection')
    expect(document.querySelectorAll('title')).toHaveLength(1)
  })

  it('shows a viewer the request, the acceptances without the signer, and no action', async () => {
    signedIn('viewer')
    mockApi('get', DETAIL, request({ acceptances: [makeAcceptance({ signer_name: null })], findings: blocked }))
    open()
    expect(await screen.findByText(/accepted on 2026-10-02 by the requester/, {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByText('The request waits for a curator’s decision.')).toBeInTheDocument()
    expect(within(screen.getByRole('main')).queryByRole('button')).not.toBeInTheDocument()
  })

  it('has a title when not found and when it failed', async () => {
    allowConsole(/API error/)
    signedIn()
    mockApiError('get', DETAIL, 404, problem(404))
    const { unmount } = open()
    expect(await screen.findByRole('heading', { name: 'Request not found' }, { timeout: 5000 })).toBeInTheDocument()
    unmount()
    signedIn()
    mockApiError('get', DETAIL, 500)
    open()
    await waitFor(() => expect(document.title).toBe('Could not load the request | Culture collection'), { timeout: 5000 })
  })
  it('offers a curator no approval while a finding blocks it, only reject and cancel', async () => {
    signedIn('curator')
    mockApi('get', DETAIL, request({ findings: blocked }))
    open()
    expect(await screen.findByText('It cannot be approved while something blocks it. Reject it, or wait for what is missing.', {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve and reserve the vials' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reject the request' })).toBeInTheDocument()
  })

  it('keeps the strains in a named region that scrolls sideways at 320 px', async () => {
    signedIn('viewer')
    mockApi('get', DETAIL, request())
    open()
    const region = await screen.findByRole('region', { name: 'Strains table' }, { timeout: 5000 })
    expect(region).toHaveAttribute('tabindex', '0')
    expect(within(region).getByRole('table', { name: 'Strains' })).toBeInTheDocument()
  })

  // jsdom's File inside Node's fetch fails (undici content-length), so the request is caught at
  // the client and its form data read; the real upload runs in e2e (distribution.spec.ts).
  it('records an acceptance with what the curator ticked: a signer who may not bind is sent as such', async () => {
    signedIn('curator')
    mockApi('get', DETAIL, request())
    open()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Record an acceptance' }, { timeout: 5000 }))
    const dialog = await screen.findByRole('dialog', { name: 'Record an acceptance of the MTA' })
    await user.type(within(dialog).getByRole('textbox', { name: 'Signed by' }), 'Karel Podpisový')
    await user.selectOptions(within(dialog).getByRole('combobox', { name: "Signer's role" }), 'responsible_scientist')
    await user.upload(within(dialog).getByLabelText('Signed copy'), new File(['%PDF-1.4'], 'signed.pdf', { type: 'application/pdf' }))
    const post = vi.spyOn(api, 'POST').mockResolvedValue({ data: request(), response: new Response('{}', { status: 201 }) })
    await user.click(within(dialog).getByRole('button', { name: 'Record the acceptance' }))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    const [, init]: unknown[] = post.mock.calls[0] ?? []
    const serializer: unknown = typeof init === 'object' && init !== null ? Reflect.get(init, 'bodySerializer') : undefined
    if (typeof serializer !== 'function') throw new Error('the acceptance is sent without its form data')
    const sent: unknown = Reflect.apply(serializer, undefined, [])
    if (!(sent instanceof FormData)) throw new Error('not form data')
    expect(Object.fromEntries([...sent.entries()].filter(([k]) => k !== 'file'))).toEqual({
      mta: line.mta?.public_id,
      signer_name: 'Karel Podpisový',
      signer_email: '',
      signer_role: 'responsible_scientist',
      authorised_signatory: 'false',
      accepted_on: new Date().toLocaleDateString('sv'),
    })
  })


  it('records no acceptance on the last valid date while the field shows an invalid one (#111)', async () => {
    signedIn('curator')
    mockApi('get', DETAIL, request())
    open()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Record an acceptance' }, { timeout: 5000 }))
    const dialog = await screen.findByRole('dialog', { name: 'Record an acceptance of the MTA' })
    await user.type(within(dialog).getByRole('textbox', { name: 'Signed by' }), 'Karel Podpisový')
    await user.selectOptions(within(dialog).getByRole('combobox', { name: "Signer's role" }), 'responsible_scientist')
    await user.upload(within(dialog).getByLabelText('Signed copy'), new File(['%PDF-1.4'], 'signed.pdf', { type: 'application/pdf' }))
    const post = vi.spyOn(api, 'POST').mockResolvedValue({ data: request(), response: new Response('{}', { status: 201 }) })
    const day = within(dialog).getByRole('textbox', { name: 'Accepted on' })
    expect(day).toHaveValue(new Date().toLocaleDateString('sv'))
    for (const typed of ['2026-13-45', '12.10.2026']) {
      await user.clear(day)
      await user.type(day, typed)
      await user.click(within(dialog).getByRole('button', { name: 'Record the acceptance' }))
      await waitFor(() => expect(day).toHaveAccessibleDescription(expect.stringContaining('Enter a date as YYYY-MM-DD')))
      expect(day).toHaveValue(typed)
      expect(post).not.toHaveBeenCalled()
    }
    post.mockRestore()
  })

  describe('the shipment', () => {
    const vial = { public_id: '00000000-0000-4000-8000-0000000000e1', label: 'MYC 3 / 1 / 1' }
    const approved = (overrides = {}) =>
      request({ status: 'approved', decided_by: 'curator', decided_at: '2026-10-20T10:00:00Z', lines: [makeRequestLine({ ...line, reserved: [vial] })], ...overrides })
    const shipped = (shipment = {}) =>
      request({
        status: 'shipped',
        decided_by: 'curator',
        decided_at: '2026-10-20T10:00:00Z',
        lines: [makeRequestLine({ ...line, reserved: [], shipped: [vial] })],
        shipment: makeShipment({ shipped_at: '2026-10-22T09:00:00Z', ...shipment }),
      })

    it('fills P650 for UN 3373, offers only its bases, and then shows the shipment and the vials sent', async () => {
      signedIn('curator')
      mockApi('get', DETAIL, approved())
      open()
      const { user, dialog } = await openShipDialog()
      expect(dialog).toHaveAccessibleDescription(/Its reserved vial leaves the collection today/)
      const transport = within(dialog).getByRole('combobox', { name: 'Transport class' })
      expect(transport).toHaveFocus()
      await user.selectOptions(transport, 'un3373')
      expect(within(dialog).getByRole('combobox', { name: 'Packing' })).toHaveValue('p650')
      const basis = within(dialog).getByRole('combobox', { name: 'Basis of the classification' })
      expect(within(basis).getAllByRole('option').map((o) => o.textContent)).toEqual(['Choose', 'Not on the indicative list of Category A', 'Professional judgement'])
      await user.selectOptions(basis, 'professional_judgement')
      await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Coolant' }), 'dry_ice')
      const calls = mockApi('post', ACTION('ship'), shipped({ transport_class: 'un3373', classification_basis: 'professional_judgement', basis_note: 'Category B.', packing_instruction: 'p650', coolant: 'dry_ice', coolant_kg: '2.50' }))
      await user.click(within(dialog).getByRole('button', { name: 'Ship' }))
      // The first field in the form's order that is wrong gets the focus; nothing is sent.
      const note = within(dialog).getByRole('textbox', { name: 'What the classification rests on' })
      expect(note).toHaveFocus()
      expect(note).toHaveAccessibleDescription(/Say what the judgement rests on/)
      expect(within(dialog).getByRole('textbox', { name: 'Coolant in kg' })).toHaveAccessibleDescription(/Give the quantity of dry ice/)
      expect(calls).toHaveLength(0)
      await user.type(note, 'Category B.')
      await user.type(within(dialog).getByRole('textbox', { name: 'Coolant in kg' }), '2,5')
      await fillPerson(user, dialog)
      await user.click(within(dialog).getByRole('button', { name: 'Ship' }))
      await waitFor(() => expect(calls).toHaveLength(1))
      expect(calls[0]?.body).toEqual({
        transport_class: 'un3373',
        classification_basis: 'professional_judgement',
        basis_note: 'Category B.',
        packing_instruction: 'p650',
        coolant: 'dry_ice',
        coolant_kg: '2.5',
        responsible_name: 'Jan Odpovědný',
        responsible_phone: '+420 555 000 111',
        carrier: 'Example Courier',
        tracking_number: '',
      })
      expect(await screen.findByText(/Shipped by curator on 2026-10-22\./, {}, { timeout: 5000 })).toBeInTheDocument()
      // Found once the dialog has faded out and the page is no longer hidden behind it.
      const shipment = await screen.findByRole('region', { name: 'Shipment' }, { timeout: 5000 })
      expect(shipment).toHaveTextContent('UN 3373, Biological substance, Category B')
      expect(shipment).toHaveTextContent('Professional judgement: Category B.')
      expect(shipment).toHaveTextContent('Dry ice (UN 1845), 2.50 kg')
      expect(shipment).toHaveTextContent('Jan Odpovědný, +420 555 000 111')
      const strains = screen.getByRole('table', { name: 'Strains' })
      expect(within(strains).getByRole('columnheader', { name: 'Shipped vials' })).toBeInTheDocument()
      expect(within(strains).getByRole('cell', { name: 'MYC 3 / 1 / 1' })).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Ship the vials' })).not.toBeInTheDocument()
    })

    it('does not ship with the last valid coolant weight while the field shows an invalid one (#111)', async () => {
      signedIn('curator')
      mockApi('get', DETAIL, approved())
      open()
      const { user, dialog } = await openShipDialog()
      await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Transport class' }), 'un3373')
      await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Basis of the classification' }), 'indicative_list')
      await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Coolant' }), 'dry_ice')
      await fillPerson(user, dialog)
      const calls = mockApi('post', ACTION('ship'), shipped())
      const kg = within(dialog).getByRole('textbox', { name: 'Coolant in kg' })
      await user.type(kg, '2,5')
      for (const [typed, message] of [
        ['2.5x', 'Enter kilograms, for example 2.5'],
        ['-1', 'Enter kilograms, for example 2.5'],
        ['2.555', 'Enter kilograms, for example 2.5'],
        ['12345', 'Enter kilograms, for example 2.5'],
        ['0', 'Give more than 0 kg'],
      ] as const) {
        await user.clear(kg)
        await user.type(kg, typed)
        await user.click(within(dialog).getByRole('button', { name: 'Ship' }))
        await waitFor(() => expect(kg).toHaveAccessibleDescription(expect.stringContaining(message)))
        expect(kg).toHaveValue(typed)
        expect(calls).toHaveLength(0)
      }
    })

    it('offers a regulated request the preparation, not the shipment in one step, and says why', async () => {
      signedIn('manager')
      mockApi('get', DETAIL, approved({ regulated: true }))
      open()
      expect(await screen.findByText(/leaves in two steps/, {}, { timeout: 5000 })).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Ship the vials' })).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Prepare the shipment' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Cancel the request' })).toBeInTheDocument()
    })

    it('stays open while it runs and shows the refusals of the server in the dialog or on the field', async () => {
      signedIn('curator')
      mockApi('get', DETAIL, approved())
      open()
      const { user, dialog } = await openShipDialog()
      await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Basis of the classification' }), 'exempt_non_pathogenic')
      await fillPerson(user, dialog)
      allowConsole(/API error (400|422)/)
      const held = holdApi('post', ACTION('ship'))
      await user.click(within(dialog).getByRole('button', { name: 'Ship' }))
      await waitFor(() => expect(held.calls).toHaveLength(1))
      await user.keyboard('{Escape}')
      expect(dialog).toBeInTheDocument()
      held.release(422, problem(422, { code: 'shipment_blocked', detail: 'MYC 3: 0 of its 1 reserved vials may still go out.' }))
      expect(await within(dialog).findByText('Nothing is shipped. MYC 3: 0 of its 1 reserved vials may still go out.')).toBeInTheDocument()
      mockApiError('post', ACTION('ship'), 422, problem(422, { code: 'second_person_required', detail: 'A second person confirms it.' }))
      await user.click(within(dialog).getByRole('button', { name: 'Ship' }))
      expect(await within(dialog).findByText(/leaves in two steps/)).toBeInTheDocument()
      mockApiError(
        'post',
        ACTION('ship'),
        400,
        validationProblem([{ attr: 'classification_basis', code: 'not_exempt', detail: 'MYC 3: risk group 2 or higher is pathogenic.' }]),
      )
      await user.click(within(dialog).getByRole('button', { name: 'Ship' }))
      expect(await within(dialog).findByRole('combobox', { name: 'Basis of the classification', description: /risk group 2 or higher is pathogenic/ })).toBeInTheDocument()
    })

    describe('in two steps (#89)', () => {
      const vialLine = makeRequestLine({ ...line, reserved: [vial] })
      const awaiting = (overrides = {}) =>
        approved({ status: 'awaiting_confirmation', regulated: true, decided_by: 'approver', lines: [vialLine], preparations: [preparation(overrides)] })

      it('a curator prepares the shipment, nothing leaves, and the page says it waits for someone else', async () => {
        signedIn('curator')
        mockApi('get', DETAIL, approved({ regulated: true, decided_by: 'approver' }))
        open()
        const user = userEvent.setup()
        await user.click(await screen.findByRole('button', { name: 'Prepare the shipment' }, { timeout: 5000 }))
        const dialog = await screen.findByRole('dialog', { name: 'Prepare the shipment of request 2026/7?' })
        expect(dialog).toHaveAccessibleDescription(/Nothing leaves yet: its reserved vial stays reserved until a second person/)
        expect(within(dialog).getByRole('combobox', { name: 'Transport class' })).toHaveFocus()
        await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Basis of the classification' }), 'exempt_non_pathogenic')
        await fillPerson(user, dialog)
        const calls = mockApi('post', ACTION('prepare-shipment'), awaiting({ confirm_refusal: 'confirm_own_preparation' }))
        await user.click(within(dialog).getByRole('button', { name: 'Prepare' }))
        await waitFor(() => expect(calls).toHaveLength(1))
        expect(calls[0]?.body).toEqual({
          transport_class: 'not_subject',
          classification_basis: 'exempt_non_pathogenic',
          basis_note: '',
          packing_instruction: 'triple_packaging',
          coolant: '',
          coolant_kg: null,
          responsible_name: 'Jan Odpovědný',
          responsible_phone: '+420 555 000 111',
          carrier: 'Example Courier',
          tracking_number: '',
        })
        expect(await screen.findByText(/The shipment was prepared by curator on 2026-10-21 and waits for a second person/, {}, { timeout: 5000 })).toBeInTheDocument()
        expect(screen.getByText('You prepared this shipment, so a different person confirms it.')).toBeInTheDocument()
        expect(screen.queryByRole('button', { name: 'Confirm the shipment' })).not.toBeInTheDocument()
        const prepared = await screen.findByRole('region', { name: 'Prepared shipment' }, { timeout: 5000 })
        expect(prepared).toHaveTextContent('Prepared bycurator on 2026-10-21')
        expect(within(screen.getByRole('table', { name: 'Strains' })).getByRole('cell', { name: 'MYC 3 / 1 / 1' })).toBeInTheDocument()
      })

      it('offers an unregulated request only the shipment in one step', async () => {
        signedIn('curator')
        mockApi('get', DETAIL, approved({ regulated: false }))
        open()
        expect(await screen.findByRole('button', { name: 'Ship the vials' }, { timeout: 5000 })).toBeInTheDocument()
        expect(screen.queryByRole('button', { name: 'Prepare the shipment' })).not.toBeInTheDocument()
        expect(screen.queryByText(/leaves in two steps/)).not.toBeInTheDocument()
      })

      it('shows the preparation not withdrawn as the one waiting, whatever the order of the list', async () => {
        signedIn('manager')
        const withdrawn = preparation({ public_id: '00000000-0000-4000-8000-0000000000f9', carrier: 'Withdrawn Courier', withdrawn_by: 'curator', withdrawn_at: '2026-10-21T09:00:00Z', withdraw_reason: 'Wrong carrier.' })
        mockApi('get', DETAIL, approved({ status: 'awaiting_confirmation', regulated: true, decided_by: 'approver', lines: [vialLine], preparations: [withdrawn, preparation()] }))
        open()
        const prepared = await screen.findByRole('region', { name: 'Prepared shipment' }, { timeout: 5000 })
        expect(prepared).toHaveTextContent('Example Courier')
        expect(prepared).not.toHaveTextContent('Withdrawn Courier')
        expect(screen.getByRole('region', { name: 'Withdrawn preparations' })).toHaveTextContent('Wrong carrier.')
      })

      it('tells the approver why they may not confirm', async () => {
        signedIn('manager')
        mockApi('get', DETAIL, awaiting({ confirm_refusal: 'confirm_own_approval' }))
        open()
        expect(await screen.findByText('You approved this request, so a different person confirms its shipment.', {}, { timeout: 5000 })).toBeInTheDocument()
        expect(screen.queryByRole('button', { name: 'Confirm the shipment' })).not.toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'Withdraw the prepared shipment' })).toBeInTheDocument()
      })

      it('a second person confirms what was prepared, in an alertdialog that stays open while it runs', async () => {
        signedIn('manager')
        mockApi('get', DETAIL, awaiting())
        open()
        const user = userEvent.setup()
        await user.click(await screen.findByRole('button', { name: 'Confirm the shipment' }, { timeout: 5000 }))
        const dialog = await screen.findByRole('alertdialog', { name: 'Confirm the shipment of request 2026/7?' })
        expect(dialog).toHaveAccessibleDescription(/Its reserved vial leaves the collection today, as prepared by curator/)
        expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus()
        // What will be recorded is shown, not the current screen.
        expect(dialog).toHaveTextContent('Example Courier')
        expect(dialog).toHaveTextContent('Jan Odpovědný, +420 555 000 111')
        allowConsole(/API error (403|409)/)
        const held = holdApi('post', ACTION('confirm-shipment'))
        await user.click(within(dialog).getByRole('button', { name: 'Confirm and ship' }))
        await waitFor(() => expect(held.calls).toHaveLength(1))
        expect(held.calls[0]?.body).toEqual({ preparation: '00000000-0000-4000-8000-0000000000f1' })
        await user.keyboard('{Escape}')
        expect(dialog).toBeInTheDocument()
        held.release(409, problem(409, { code: 'preparation_changed' }))
        expect(await within(dialog).findByText('The prepared shipment changed meanwhile. Close this and read it again.')).toBeInTheDocument()
        mockApiError('post', ACTION('confirm-shipment'), 403, problem(403, { code: 'confirm_own_preparation' }))
        await user.click(within(dialog).getByRole('button', { name: 'Confirm and ship' }))
        expect(await within(dialog).findByText('You prepared this shipment, so a different person confirms it.')).toBeInTheDocument()
        mockApi(
          'post',
          ACTION('confirm-shipment'),
          request({
            status: 'shipped',
            decided_by: 'approver',
            decided_at: '2026-10-20T10:00:00Z',
            regulated: true,
            lines: [makeRequestLine({ ...line, reserved: [], shipped: [vial] })],
            preparations: [preparation()],
            shipment: makeShipment({ classified_by: 'curator', classified_at: '2026-10-21T08:00:00Z', shipped_by: 'manager', shipped_at: '2026-10-22T09:00:00Z', preparation: '00000000-0000-4000-8000-0000000000f1' }),
          }),
        )
        await user.click(within(dialog).getByRole('button', { name: 'Confirm and ship' }))
        expect(await screen.findByText(/Prepared by curator on 2026-10-21, confirmed and shipped by manager on 2026-10-22\./, {}, { timeout: 5000 })).toBeInTheDocument()
        const shipment = await screen.findByRole('region', { name: 'Shipment' }, { timeout: 5000 })
        expect(shipment).toHaveTextContent('Prepared and classified bycurator on 2026-10-21')
        expect(shipment).toHaveTextContent('Confirmed bymanager on 2026-10-22')
        expect(screen.queryByRole('region', { name: 'Prepared shipment' })).not.toBeInTheDocument()
      })

      it('withdraws the preparation with a reason and lists it as withdrawn', async () => {
        signedIn('curator')
        mockApi('get', DETAIL, awaiting({ confirm_refusal: 'confirm_own_preparation' }))
        open()
        const user = userEvent.setup()
        await user.click(await screen.findByRole('button', { name: 'Withdraw the prepared shipment' }, { timeout: 5000 }))
        const dialog = await screen.findByRole('alertdialog', { name: 'Withdraw the prepared shipment of request 2026/7?' })
        expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus()
        const withdrawn = preparation({ withdrawn_by: 'curator', withdrawn_at: '2026-10-22T07:00:00Z', withdraw_reason: 'The courier cannot come.' })
        const calls = mockApi('post', ACTION('withdraw-shipment'), approved({ regulated: true, decided_by: 'approver', preparations: [withdrawn] }))
        await user.click(within(dialog).getByRole('button', { name: 'Withdraw the shipment' }))
        expect(calls).toHaveLength(0)
        await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'The courier cannot come.')
        await user.click(within(dialog).getByRole('button', { name: 'Withdraw the shipment' }))
        await waitFor(() => expect(calls[0]?.body).toEqual({ reason: 'The courier cannot come.' }))
        const list = await screen.findByRole('region', { name: 'Withdrawn preparations' }, { timeout: 5000 })
        expect(list).toHaveTextContent('Prepared by curator on 2026-10-21, withdrawn by curator on 2026-10-22: The courier cannot come.')
        expect(screen.getByRole('button', { name: 'Prepare the shipment' })).toBeInTheDocument()
      })

      it('shows a viewer the prepared shipment without the person who answers for it, and no action', async () => {
        signedIn('viewer')
        mockApi('get', DETAIL, awaiting({ responsible_name: null, responsible_phone: null }))
        open()
        const prepared = await screen.findByRole('region', { name: 'Prepared shipment' }, { timeout: 5000 })
        expect(prepared).toHaveTextContent('Example Courier')
        expect(prepared).not.toHaveTextContent('Responsible person')
        expect(within(screen.getByRole('main')).queryByRole('button')).not.toBeInTheDocument()
      })
    })

    it('shows a viewer the shipment without the person who answers for it', async () => {
      signedIn('viewer')
      mockApi('get', DETAIL, shipped({ responsible_name: null, responsible_phone: null }))
      open()
      const shipment = await screen.findByRole('region', { name: 'Shipment' }, { timeout: 5000 })
      expect(shipment).toHaveTextContent('Example Courier')
      expect(shipment).not.toHaveTextContent('Responsible person')
      expect(within(screen.getByRole('main')).queryByRole('button')).not.toBeInTheDocument()
    })
  })


  it('lists the documents of the shipment to everyone and opens them only for curators and managers', async () => {
    const note = makeShipmentDocument({ public_id: '00000000-0000-4000-8000-0000000000e1', text_sha256: '0123456789ab'.repeat(5) + 'cdef' })
    const entry = makeShipmentDocument({ public_id: '00000000-0000-4000-8000-0000000000e2', kind: 'register_entry', strain: 'MYC 3' })
    const shipped = request({ status: 'shipped', decided_by: 'curator', shipment: makeShipment({ documents: [note, entry] }) })
    signedIn('viewer')
    mockApi('get', DETAIL, shipped)
    const { unmount } = open()
    const listed = await screen.findByRole('list', { name: 'Documents of the shipment' }, { timeout: 5000 })
    expect(within(listed).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      'Delivery note, SHA-256 0123456789ab',
      `Register entry and handover protocol for MYC 3, SHA-256 ${'3f'.repeat(6)}`,
    ])
    expect(within(listed).queryAllByRole('link')).toHaveLength(0)
    expect(screen.getByText('Curators and managers open the documents: they name the responsible person.')).toBeInTheDocument()
    unmount()
    signedIn('curator')
    mockApi('get', DETAIL, shipped)
    open()
    const own = await screen.findByRole('list', { name: 'Documents of the shipment' }, { timeout: 5000 })
    expect(within(own).getByRole('link', { name: 'View and print: Delivery note' })).toHaveAttribute('href', `/labs/${LAB_ID}/shipment-documents/${note.public_id}`)
    expect(within(own).getByRole('link', { name: 'Download: Register entry and handover protocol for MYC 3' })).toHaveAttribute(
      'href',
      `${window.location.origin}/api/v1/labs/${LAB_ID}/shipment-documents/${entry.public_id}/download/`,
    )
    expect(screen.queryByText(/Curators and managers open the documents/)).not.toBeInTheDocument()
  })

  it('says when a shipment has no documents, as one recorded before they were written', async () => {
    signedIn('curator')
    mockApi('get', DETAIL, request({ status: 'shipped', decided_by: 'curator', shipment: makeShipment() }))
    open()
    expect(await screen.findByText('This shipment was recorded before its documents were written by the app.', {}, { timeout: 5000 })).toBeInTheDocument()
  })
})
