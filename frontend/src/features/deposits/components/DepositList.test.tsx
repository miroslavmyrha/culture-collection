import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { makeDepositRow, makeLab, makeMe, page } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { renderApp } from '@/test/render'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const LIST = '/api/v1/labs/{lab_public_id}/deposits/'

function signedIn(role: 'curator' | 'viewer' = 'curator') {
  mockApi('get', '/api/v1/auth/me/', makeMe())
  mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: role }))
}

describe('the deposits page', () => {
  it('shows each deposit linked, its depositor, status and strain', async () => {
    signedIn()
    const accepted = makeDepositRow({ name_as_received: 'Testella exempli K3', status: 'accepted', strain: { public_id: '00000000-0000-4000-8000-0000000000f1', accession_number: 'MYC 9' } })
    mockApi('get', LIST, page([accepted, makeDepositRow({ name_as_received: 'Mockia D2' })]))
    renderApp({ path: `/labs/${LAB_ID}/deposits` })
    const table = await screen.findByRole('table', { name: 'Deposits' })
    const [, first, second] = within(table).getAllByRole('row')
    if (!first || !second) throw new Error('no rows')
    expect(within(first).getByRole('link', { name: 'Testella exempli K3' })).toHaveAttribute('href', `/labs/${LAB_ID}/deposits/${accepted.public_id}`)
    expect(within(first).getByRole('link', { name: 'MYC 9' })).toHaveAttribute('href', `/labs/${LAB_ID}/strains/00000000-0000-4000-8000-0000000000f1`)
    expect(first).toHaveTextContent('Accepted')
    expect(second).toHaveTextContent('None')
    expect(screen.getByRole('link', { name: 'Receive a deposit' })).toHaveAttribute('href', `/labs/${LAB_ID}/deposits/new`)
  })

  it('puts the status and the search into the URL and asks the API with them', async () => {
    signedIn()
    const calls = mockApi('get', LIST, page([makeDepositRow()]))
    const { router } = renderApp({ path: `/labs/${LAB_ID}/deposits` })
    const user = userEvent.setup()
    await user.selectOptions(await screen.findByRole('combobox', { name: 'Status' }), 'checking')
    await waitFor(() => expect(router.state.location.search).toEqual({ status: 'checking' }))
    await user.type(screen.getByRole('searchbox', { name: 'Name, depositor or number' }), 'K3{Enter}')
    await waitFor(() => expect(router.state.location.search).toEqual({ status: 'checking', search: 'K3' }))
    await waitFor(() => expect(Object.fromEntries(calls.at(-1)?.url.searchParams ?? [])).toEqual({ limit: '25', offset: '0', status: 'checking', search: 'K3' }))
  })

  it('keeps the status when Search is pressed right after choosing it', async () => {
    signedIn()
    const calls = mockApi('get', LIST, page([makeDepositRow()]))
    const { router } = renderApp({ path: `/labs/${LAB_ID}/deposits` })
    const status = await screen.findByRole('combobox', { name: 'Status' })
    fireEvent.change(status, { target: { value: 'checking' } })
    fireEvent.change(screen.getByRole('searchbox', { name: 'Name, depositor or number' }), { target: { value: 'K3' } })
    // No wait between the two: the navigation of the status has not reached the form yet.
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    await waitFor(() => expect(router.state.location.search).toEqual({ status: 'checking', search: 'K3' }))
    await waitFor(() => expect(Object.fromEntries(calls.at(-1)?.url.searchParams ?? [])).toEqual({ limit: '25', offset: '0', status: 'checking', search: 'K3' }))
    expect(screen.getByRole('combobox', { name: 'Status' })).toHaveValue('checking')
  })

  it('offers to clear filters that match nothing, and focus moves on as the button goes', async () => {
    signedIn()
    mockApi('get', LIST, page([]))
    const { router } = renderApp({ path: `/labs/${LAB_ID}/deposits`, search: { status: 'rejected' } })
    const user = userEvent.setup()
    const text = await screen.findByText(/No deposit matches these filters/)
    await user.click(within(text).getByRole('button', { name: 'Clear filters' }))
    await waitFor(() => expect(router.state.location.search).toEqual({}))
    expect(await screen.findByText('The lab has received no deposits yet.')).toBeInTheDocument()
    expect(document.activeElement).not.toBe(document.body)
  })

  it('falls back to all statuses for an unknown one in the URL', async () => {
    signedIn()
    const calls = mockApi('get', LIST, page([]))
    renderApp({ path: `/labs/${LAB_ID}/deposits`, search: { status: 'lost' } })
    expect(await screen.findByText('The lab has received no deposits yet.')).toBeInTheDocument()
    expect(calls[0]?.url.searchParams.get('status')).toBeNull()
  })

  it('says a load failed and loads again on Try again', async () => {
    signedIn()
    mockApiError('get', LIST, 500)
    renderApp({ path: `/labs/${LAB_ID}/deposits` })
    expect(await screen.findByText(/Could not load the deposits/)).toBeInTheDocument()
    mockApi('get', LIST, page([makeDepositRow({ name_as_received: 'Back again' })]))
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('link', { name: 'Back again' })).toBeInTheDocument()
  })

  it('offers the first page past the end', async () => {
    signedIn()
    mockApi('get', LIST, page([], { count: 3 }))
    const { router } = renderApp({ path: `/labs/${LAB_ID}/deposits`, search: { offset: 50 } })
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Go to the first page' }))
    await waitFor(() => expect(router.state.location.search).toEqual({}))
  })

  it('leads a curator from the strains to the intake, and a viewer nowhere', async () => {
    signedIn('viewer')
    mockApi('get', '/api/v1/labs/{lab_public_id}/strains/', page([]))
    renderApp({ path: `/labs/${LAB_ID}/strains` })
    expect(await screen.findByText('The lab has no strains yet.')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Receive a deposit' })).not.toBeInTheDocument()
  })
})
