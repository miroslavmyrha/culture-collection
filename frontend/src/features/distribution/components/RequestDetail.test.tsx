import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { allowConsole } from '@/test/console'
import { makeAcceptance, makeFinding, makeLab, makeMe, makeRequest, makeRequestLine, makeShipment, problem, validationProblem } from '@/test/factories'
import { holdApi, mockApi, mockApiError } from '@/test/mockApi'
import { renderApp } from '@/test/render'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const REQUEST_ID = '00000000-0000-4000-8000-0000000000a1'
const DETAIL = '/api/v1/labs/{lab_public_id}/requests/{public_id}/'
const ACTION = (name: 'approve' | 'reject' | 'cancel' | 'ship') => `/api/v1/labs/{lab_public_id}/requests/{public_id}/${name}/` as const

function signedIn(role: 'viewer' | 'technician' | 'curator' | 'manager' = 'curator') {
  mockApi('get', '/api/v1/auth/me/', makeMe())
  mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: role }))
}

const line = makeRequestLine({ public_id: '00000000-0000-4000-8000-0000000000b1', strain: { public_id: '00000000-0000-4000-8000-0000000000c1', accession_number: 'MYC 3', taxon: 'Mockia vulgaris', risk_group: 2 } })
const request = (overrides = {}) => makeRequest({ public_id: REQUEST_ID, number: '2026/7', lines: [line], ...overrides })
const open = () => renderApp({ path: `/labs/${LAB_ID}/requests/${REQUEST_ID}` })
const blocked = [makeFinding({ code: 'loa_missing', sentence: 'MYC 3 is a quarantine pest: the requester shows no valid Letter of Authority that names Mockia vulgaris.', line: line.public_id })]
const regulated = [makeFinding({ code: 'regulated', severity: 'manager', sentence: 'MYC 3 is regulated (dual_use): a manager approves it.', line: line.public_id })]

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

    it('says why a regulated request is not shipped here, and offers no shipment', async () => {
      signedIn('manager')
      mockApi('get', DETAIL, approved({ regulated: true }))
      open()
      expect(await screen.findByText(/shipped only when a second person confirms it/, {}, { timeout: 5000 })).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Ship the vials' })).not.toBeInTheDocument()
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
      expect(await within(dialog).findByText(/shipped only when a second person confirms it/)).toBeInTheDocument()
      mockApiError(
        'post',
        ACTION('ship'),
        400,
        validationProblem([{ attr: 'classification_basis', code: 'not_exempt', detail: 'MYC 3: risk group 2 or higher is pathogenic.' }]),
      )
      await user.click(within(dialog).getByRole('button', { name: 'Ship' }))
      expect(await within(dialog).findByRole('combobox', { name: 'Basis of the classification', description: /risk group 2 or higher is pathogenic/ })).toBeInTheDocument()
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

})
