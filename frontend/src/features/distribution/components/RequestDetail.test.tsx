import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeAcceptance, makeFinding, makeLab, makeMe, makeRequest, makeRequestLine, problem } from '@/test/factories'
import { holdApi, mockApi, mockApiError } from '@/test/mockApi'
import { renderApp } from '@/test/render'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const REQUEST_ID = '00000000-0000-4000-8000-0000000000a1'
const DETAIL = '/api/v1/labs/{lab_public_id}/requests/{public_id}/'
const ACTION = (name: 'approve' | 'reject' | 'cancel') => `/api/v1/labs/{lab_public_id}/requests/{public_id}/${name}/` as const

function signedIn(role: 'viewer' | 'technician' | 'curator' | 'manager' = 'curator') {
  mockApi('get', '/api/v1/auth/me/', makeMe())
  mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: role }))
}

const line = makeRequestLine({ public_id: '00000000-0000-4000-8000-0000000000b1', strain: { public_id: '00000000-0000-4000-8000-0000000000c1', accession_number: 'MYC 3', taxon: 'Mockia vulgaris', risk_group: 2 } })
const request = (overrides = {}) => makeRequest({ public_id: REQUEST_ID, number: '2026/7', lines: [line], ...overrides })
const open = () => renderApp({ path: `/labs/${LAB_ID}/requests/${REQUEST_ID}` })
const blocked = [makeFinding({ code: 'loa_missing', sentence: 'MYC 3 is a quarantine pest: the requester shows no valid Letter of Authority that names Mockia vulgaris.', line: line.public_id })]
const regulated = [makeFinding({ code: 'regulated', severity: 'manager', sentence: 'MYC 3 is regulated (dual_use): a manager approves it.', line: line.public_id })]

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
})
