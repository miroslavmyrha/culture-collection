import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeDepositor, makeLab, makeMe, page, problem, validationProblem } from '@/test/factories'
import { holdApi, mockApi, mockApiError, recordRequests } from '@/test/mockApi'
import { renderApp, renderWithProviders } from '@/test/render'
import type { DepositorListParams } from '../schemas'
import { DepositorList } from './DepositorList'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const LIST = '/api/v1/labs/{lab_public_id}/depositors/'
const ONE = '/api/v1/labs/{lab_public_id}/depositors/{public_id}/'
const PARAMS: DepositorListParams = { limit: 25, offset: 0 }
// Invented people at example.org: a depositor's contact is personal data.
const jana = makeDepositor({ name: 'Jana Vzorová', email: 'jana@example.org', institution: 'Example University' })

async function renderList(params: DepositorListParams = PARAMS) {
  const onOffsetChange = vi.fn<(offset: number) => void>()
  const onSearch = vi.fn<(text: string | undefined) => void>()
  const view = await renderWithProviders(<DepositorList labId={LAB_ID} params={params} onOffsetChange={onOffsetChange} onSearch={onSearch} />)
  return { ...view, onOffsetChange, onSearch, user: userEvent.setup() }
}

describe('DepositorList', { timeout: 15_000 }, () => {
  it('shows each depositor with the contact, and an erased one by that word', async () => {
    mockApi('get', LIST, page([jana, makeDepositor({ name: '', email: '', institution: 'Old Institute', erased: true })]))
    await renderList()
    expect(screen.getByText('Loading the depositors…')).toBeInTheDocument()
    const table = await screen.findByRole('table', { name: 'Depositors' })
    const [, first, second] = within(table).getAllByRole('row')
    if (!first || !second) throw new Error('no rows')
    expect(within(first).getAllByRole('cell').map((cell) => cell.textContent)).toEqual(['Jana Vzorová', 'Example University', 'jana@example.org', 'Change'])
    expect(within(second).getAllByRole('cell').map((cell) => cell.textContent)).toEqual(['Erased contact', 'Old Institute', '', ''])
  })

  it('says when the lab has none, and when a search finds none', async () => {
    mockApi('get', LIST, page([]))
    await renderList()
    expect(await screen.findByText('The lab has no depositors yet.')).toBeInTheDocument()
  })

  it('shows a load error with a retry that works', async () => {
    allowConsole(/API error 500/)
    mockApiError('get', LIST, 500)
    const { user } = await renderList()
    const retry = await screen.findByRole('button', { name: 'Try again' }, { timeout: 5000 })
    mockApi('get', LIST, page([jana]))
    await user.click(retry)
    expect(await screen.findByRole('table', { name: 'Depositors' })).toBeInTheDocument()
  })

  it('submits the search text, trimmed', async () => {
    mockApi('get', LIST, page([jana]))
    const { user, onSearch } = await renderList()
    await user.type(await screen.findByRole('searchbox', { name: 'Name or institution' }), '  vzor {Enter}')
    expect(onSearch).toHaveBeenCalledWith('vzor')
  })

  it('adds a depositor: the payload, the CSRF token, the list refreshed, the focus back on the button', async () => {
    const reads = mockApi('get', LIST, page([]))
    const calls = mockApi('post', LIST, makeDepositor({ name: 'Petr Příklad' }))
    const { user } = await renderList()
    const add = await screen.findByRole('button', { name: 'Add a depositor' })
    await user.click(add)
    const dialog = await screen.findByRole('dialog', { name: 'Add a depositor' })
    expect(within(dialog).getByRole('textbox', { name: 'Name' })).toHaveFocus()
    await user.type(within(dialog).getByRole('textbox', { name: 'Name' }), ' Petr Příklad ')
    await user.type(within(dialog).getByRole('textbox', { name: 'E-mail' }), 'petr@example.org')
    await user.type(within(dialog).getByRole('textbox', { name: 'Institution' }), 'Example Institute')
    await user.click(within(dialog).getByRole('button', { name: 'Add the depositor' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument(), { timeout: 5000 })
    expect(calls[0]?.body).toEqual({ name: 'Petr Příklad', email: 'petr@example.org', postal_address: '', institution: 'Example Institute' })
    expect(calls[0]?.headers.get('X-CSRFToken')).toBe('test-token')
    await waitFor(() => expect(reads).toHaveLength(2)) // the list on screen was fetched again
    await waitFor(() => expect(add).toHaveFocus(), { timeout: 5000 })
  })

  it('refuses an empty name and a wrong e-mail without a request', async () => {
    mockApi('get', LIST, page([]))
    const calls = recordRequests('post', LIST)
    const { user } = await renderList()
    await user.click(await screen.findByRole('button', { name: 'Add a depositor' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByRole('textbox', { name: 'E-mail' }), 'not an address')
    await user.click(within(dialog).getByRole('button', { name: 'Add the depositor' }))
    const name = within(dialog).getByRole('textbox', { name: 'Name' })
    await waitFor(() => expect(name).toHaveAccessibleDescription('Enter the name'), { timeout: 5000 })
    expect(name).toHaveFocus()
    expect(within(dialog).getByRole('textbox', { name: 'E-mail' })).toHaveAttribute('aria-invalid', 'true')
    expect(calls).toHaveLength(0)
  })

  it('changes a depositor with its values filled in, and puts a server error on its field', async () => {
    mockApi('get', LIST, page([jana]))
    const calls = mockApiError('put', ONE, 400, validationProblem([{ attr: 'email', code: 'invalid', detail: 'Enter a valid email address.' }]))
    const { user } = await renderList()
    await user.click(await screen.findByRole('button', { name: 'Change Jana Vzorová' }))
    const dialog = await screen.findByRole('dialog', { name: 'Change the depositor' })
    expect(within(dialog).getByRole('textbox', { name: 'Name' })).toHaveValue('Jana Vzorová')
    await user.click(within(dialog).getByRole('button', { name: 'Save the depositor' }))
    const email = within(dialog).getByRole('textbox', { name: 'E-mail' })
    await waitFor(() => expect(email).toHaveAccessibleDescription('Enter a valid email address.'), { timeout: 5000 })
    expect(email).toHaveFocus()
    expect(calls[0]?.url.pathname).toBe(`/api/v1/labs/${LAB_ID}/depositors/${jana.public_id}/`)
  })

  it('says so when the contact was erased meanwhile, in the dialog', async () => {
    mockApi('get', LIST, page([jana]))
    mockApiError('put', ONE, 409, problem(409, { code: 'contact_erased', detail: 'server words' }))
    const { user } = await renderList()
    await user.click(await screen.findByRole('button', { name: 'Change Jana Vzorová' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Save the depositor' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('This contact was erased. It can no longer be changed.')
    expect(screen.queryByText('server words')).not.toBeInTheDocument()
  })

  it('keeps the dialog open and the button focusable while it saves', async () => {
    mockApi('get', LIST, page([jana]))
    const held = holdApi('put', ONE)
    const { user } = await renderList()
    await user.click(await screen.findByRole('button', { name: 'Change Jana Vzorová' }))
    const dialog = await screen.findByRole('dialog')
    const save = within(dialog).getByRole('button', { name: 'Save the depositor' })
    await user.click(save)
    await waitFor(() => expect(save).toHaveAttribute('aria-disabled', 'true'), { timeout: 5000 })
    await user.keyboard('{Escape}')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    await user.click(save)
    expect(held.calls).toHaveLength(1)
    held.release(200, jana)
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument(), { timeout: 5000 })
  })
})

function signedIn(role: 'viewer' | 'curator') {
  mockApi('get', '/api/v1/auth/me/', makeMe())
  mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: role }))
}

describe('the depositors page', { timeout: 15_000 }, () => {
  it('puts the search into the URL and asks the API with it', async () => {
    signedIn('curator')
    const calls = mockApi('get', LIST, page([jana]))
    const { router } = renderApp({ path: `/labs/${LAB_ID}/depositors` })
    const user = userEvent.setup()
    await user.type(await screen.findByRole('searchbox', { name: 'Name or institution' }, { timeout: 5000 }), 'vzor{Enter}')
    await waitFor(() => expect(router.state.location.search).toEqual({ search: 'vzor' }), { timeout: 5000 })
    await waitFor(() => expect(calls.at(-1)?.url.searchParams.get('search')).toBe('vzor'), { timeout: 5000 })
  })

  it('tells a viewer that depositors are for curators, without a list', async () => {
    signedIn('viewer')
    mockApiError('get', LIST, 403, problem(403))
    renderApp({ path: `/labs/${LAB_ID}/depositors` })
    expect(await screen.findByText(/Only curators and managers see depositors/, undefined, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add a depositor' })).not.toBeInTheDocument()
  })
})
