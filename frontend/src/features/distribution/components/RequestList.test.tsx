import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeLab, makeMe, makeRequestRow, page } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { renderApp } from '@/test/render'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const LIST = '/api/v1/labs/{lab_public_id}/requests/'

function signedIn(role: 'viewer' | 'curator' = 'viewer') {
  mockApi('get', '/api/v1/auth/me/', makeMe())
  mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: role }))
}

describe('the request list', { timeout: 20_000 }, () => {
  it('lists the requests with their requester, use, size and status; a viewer may not enter one', async () => {
    signedIn()
    mockApi('get', LIST, page([makeRequestRow({ number: '2026/2', regulated: true, line_count: 2, vial_count: 3, status: 'approved' })]))
    renderApp({ path: `/labs/${LAB_ID}/requests` })
    const table = await screen.findByRole('table', { name: 'Requests' }, { timeout: 5000 })
    expect(within(table).getAllByRole('row')[1]).toHaveTextContent('2026/2Example Institute of Microbiology, CzechiaNon-commercial research2 strains, 3 vials, regulatedApproved, vials reserved')
    expect(within(table).getByRole('link', { name: 'Request 2026/2' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Enter a request' })).not.toBeInTheDocument()
  })

  it('keeps the filters in the URL and sends them', async () => {
    signedIn('curator')
    const calls = mockApi('get', LIST, page([]))
    const { router } = renderApp({ path: `/labs/${LAB_ID}/requests` })
    expect(await screen.findByText('No request has been entered yet.', {}, { timeout: 5000 })).toBeInTheDocument()
    const user = userEvent.setup()
    await user.selectOptions(screen.getByRole('combobox', { name: 'Status' }), 'submitted')
    await user.type(screen.getByRole('searchbox', { name: 'Number, requester or strain' }), '2026/7{Enter}')
    await waitFor(() => expect(router.state.location.search).toEqual({ status: 'submitted', search: '2026/7' }))
    await waitFor(() => expect(calls.at(-1)?.url.searchParams.get('search')).toBe('2026/7'))
    expect(calls.at(-1)?.url.searchParams.get('status')).toBe('submitted')
    expect(await screen.findByText('No request matches these filters.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Enter a request' })).toBeInTheDocument()
  })

  it('offers a retry when the first load failed', async () => {
    allowConsole(/API error 500/)
    signedIn()
    mockApiError('get', LIST, 500)
    renderApp({ path: `/labs/${LAB_ID}/requests` })
    expect(await screen.findByRole('button', { name: 'Try again' }, { timeout: 5000 })).toBeInTheDocument()
  })
})
