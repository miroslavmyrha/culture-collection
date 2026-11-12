import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeVratAccess, problem, validationProblem } from '@/test/factories'
import { holdApi, mockApi, mockApiError } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { VratAccessList } from './VratAccessList'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const LIST = '/api/v1/labs/{lab_public_id}/vrat-access/'
const END = '/api/v1/labs/{lab_public_id}/vrat-access/{public_id}/end/'

const alice = makeVratAccess({ username: 'alice', first_name: 'Alice', last_name: 'Adams', granted_by: 'carol', reason: 'works in the BSL-3 suite' })
const bob = makeVratAccess({ username: 'bob', granted_at: '2026-03-01T08:00:00Z', ended_at: '2026-09-01T08:00:00Z', ended_by: 'carol', end_reason: 'The member left the lab.' })
const dan = makeVratAccess({ username: 'dan', ended_at: '2026-09-02T08:00:00Z', ended_by: null, end_reason: 'The account was deactivated.' })

async function render() {
  const view = await renderWithProviders(<VratAccessList labId={LAB_ID} />)
  return { ...view, user: userEvent.setup() }
}

const rowsOf = (name: string) =>
  within(screen.getByRole('table', { name }))
    .getAllByRole('row')
    .slice(1)
    .map((row) => within(row).getAllByRole('cell').map((cell) => cell.textContent))

describe('the VRAT access list on the lab page (act 281/2002 Sb., § 14a(4))', () => {
  it('lists who has access now and the entries that ended, and links to the printable list', async () => {
    mockApi('get', LIST, [alice, bob, dan])
    await render()
    await screen.findByRole('table', { name: 'People with VRAT access' })
    expect(rowsOf('People with VRAT access')).toEqual([['alice', 'Alice Adams', expect.stringMatching(/^2026-10-01 \d\d:00$/), 'carol', 'works in the BSL-3 suite', 'End access']])
    expect(rowsOf('Ended entries of the VRAT access list')).toEqual([
      ['bob', expect.stringMatching(/^2026-03-01/), expect.stringMatching(/^2026-09-01/), 'carol', 'The member left the lab.'],
      ['dan', expect.any(String), expect.stringMatching(/^2026-09-02/), 'the system', 'The account was deactivated.'],
    ])
    // No control inside the ended table: it is a named region with a tab stop of its own.
    expect(screen.getByRole('region', { name: 'Ended entries table' })).toHaveAttribute('tabindex', '0')
    expect(screen.getByRole('link', { name: 'Print the VRAT access list' })).toHaveAttribute('href', `/labs/${LAB_ID}/vrat-access`)
  })

  it('says so when nobody is on it, and shows no ended table', async () => {
    mockApi('get', LIST, [])
    await render()
    expect(await screen.findByText('Nobody is on the VRAT access list.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('shows a failure to load with a retry that works', async () => {
    allowConsole(/API error 500/)
    mockApiError('get', LIST, 500)
    const { user } = await render()
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load the VRAT access list.')
    mockApi('get', LIST, [alice])
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('cell', { name: 'alice' })).toBeInTheDocument()
  })

  it('puts a member on it with a reason, asked for before any request', async () => {
    mockApi('get', LIST, [])
    const calls = mockApi('post', LIST, makeVratAccess({ username: 'eve' }))
    const { user } = await render()
    const form = await screen.findByRole('form', { name: 'Put a member on the VRAT access list' })
    await user.click(within(form).getByRole('button', { name: 'Put on the list' }))
    const username = within(form).getByRole('textbox', { name: 'Username' })
    expect(username).toHaveAccessibleDescription('An active member of this lab Enter a username')
    expect(username).toHaveFocus()
    expect(within(form).getByRole('textbox', { name: 'Reason' })).toHaveAccessibleDescription('Stored for good. Name no person. Say why')
    expect(calls).toHaveLength(0)
    await user.type(username, ' eve ')
    await user.type(within(form).getByRole('textbox', { name: 'Reason' }), ' takes over the BSL-3 work ')
    mockApi('get', LIST, [makeVratAccess({ username: 'eve' })])
    await user.click(within(form).getByRole('button', { name: 'Put on the list' }))
    expect(await within(form).findByText('Put eve on the VRAT access list.')).toBeInTheDocument()
    expect(calls[0]?.body).toEqual({ username: 'eve', reason: 'takes over the BSL-3 work' })
    expect(calls[0]?.headers.get('X-CSRFToken')).toBe('test-token')
    expect(await screen.findByRole('cell', { name: 'eve' })).toBeInTheDocument()
    expect(username).toHaveValue('')
  })

  it.each([
    ['an unknown or inactive user', validationProblem([{ attr: 'username', code: 'does_not_exist', detail: 'Invalid user.' }]), 'No active member of this lab has this username'],
    ['an active user of another lab', problem(400, { code: 'invalid_user', errors: [{ attr: 'username', code: 'invalid_user', detail: 'x' }] }), 'No active member of this lab has this username'],
    ['a member on the list already', problem(400, { code: 'already_on_list', errors: [{ attr: 'username', code: 'already_on_list', detail: 'x' }] }), 'This member is on the list already'],
  ])('puts the error of %s on the username, focused', async (_, body, message) => {
    allowConsole(/API error 400/)
    mockApi('get', LIST, [])
    mockApiError('post', LIST, 400, body)
    const { user } = await render()
    const form = await screen.findByRole('form', { name: 'Put a member on the VRAT access list' })
    const username = within(form).getByRole('textbox', { name: 'Username' })
    await user.type(username, 'frank')
    await user.type(within(form).getByRole('textbox', { name: 'Reason' }), 'r')
    await user.click(within(form).getByRole('button', { name: 'Put on the list' }))
    await waitFor(() => expect(username).toHaveAccessibleDescription(`An active member of this lab ${message}`))
    expect(username).toHaveFocus()
  })

  it('puts "Say why" on the reason, focused, when the server wants one', async () => {
    allowConsole(/API error 400/)
    mockApi('get', LIST, [])
    mockApiError('post', LIST, 400, problem(400, { code: 'reason_required' }))
    const { user } = await render()
    const form = await screen.findByRole('form', { name: 'Put a member on the VRAT access list' })
    const reason = within(form).getByRole('textbox', { name: 'Reason' })
    await user.type(within(form).getByRole('textbox', { name: 'Username' }), 'frank')
    await user.type(reason, 'r')
    await user.click(within(form).getByRole('button', { name: 'Put on the list' }))
    await waitFor(() => expect(reason).toHaveAccessibleDescription('Stored for good. Name no person. Say why'))
    expect(reason).toHaveFocus()
  })

  it('shows any other failure of putting a member on the list as an alert on the form', async () => {
    allowConsole(/API error 500/)
    mockApi('get', LIST, [])
    mockApiError('post', LIST, 500, problem(500, { code: 'error' }))
    const { user } = await render()
    const form = await screen.findByRole('form', { name: 'Put a member on the VRAT access list' })
    await user.type(within(form).getByRole('textbox', { name: 'Username' }), 'frank')
    await user.type(within(form).getByRole('textbox', { name: 'Reason' }), 'r')
    await user.click(within(form).getByRole('button', { name: 'Put on the list' }))
    expect(await within(form).findByRole('alert')).toBeInTheDocument()
  })

  it('keeps the button focusable while the request runs and sends once', async () => {
    mockApi('get', LIST, [])
    const held = holdApi('post', LIST)
    const { user } = await render()
    const form = await screen.findByRole('form', { name: 'Put a member on the VRAT access list' })
    await user.type(within(form).getByRole('textbox', { name: 'Username' }), 'eve')
    await user.type(within(form).getByRole('textbox', { name: 'Reason' }), 'r')
    const button = within(form).getByRole('button', { name: 'Put on the list' })
    await user.click(button)
    await waitFor(() => expect(button).toHaveAttribute('aria-disabled', 'true'))
    await user.click(button)
    expect(button).toHaveFocus()
    expect(held.calls).toHaveLength(1)
    held.release(201, makeVratAccess({ username: 'eve' }))
    expect(await within(form).findByText('Put eve on the VRAT access list.')).toBeInTheDocument()
  })

  it('ends an entry with a reason; focus goes to the heading once the last End button is gone', async () => {
    mockApi('get', LIST, [alice])
    const calls = mockApi('post', END, undefined)
    const { user } = await render()
    await user.click(await screen.findByRole('button', { name: 'End VRAT access of alice' }))
    const dialog = await screen.findByRole('dialog', { name: 'End VRAT access of alice' })
    expect(dialog).toHaveAccessibleDescription(/The entry stays in the list's history with the reason\./)
    const reason = within(dialog).getByRole('textbox', { name: 'Reason' })
    expect(reason).toHaveFocus()
    await user.click(within(dialog).getByRole('button', { name: 'End access' }))
    expect(reason).toHaveAccessibleDescription('Stored for good with the change. Name no person. Say why')
    expect(calls).toHaveLength(0)
    await user.type(reason, ' left for another project ')
    mockApi('get', LIST, [{ ...alice, ended_at: '2026-11-03T10:00:00Z', ended_by: 'carol', end_reason: 'left for another project' }])
    await user.click(within(dialog).getByRole('button', { name: 'End access' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ reason: 'left for another project' })
    expect(calls[0]?.url.pathname).toBe(`/api/v1/labs/${LAB_ID}/vrat-access/${alice.public_id}/end/`)
    expect(await screen.findByText('Nobody is on the VRAT access list.')).toBeInTheDocument()
    expect(rowsOf('Ended entries of the VRAT access list')[0]?.[4]).toBe('left for another project')
    await waitFor(() => expect(screen.getByRole('heading', { level: 2, name: 'VRAT access list' })).toHaveFocus())
  })

  it('says inside the dialog when the entry ended meanwhile', async () => {
    allowConsole(/API error 409/)
    mockApi('get', LIST, [alice])
    mockApiError('post', END, 409, problem(409, { code: 'vrat_access_ended' }))
    const { user } = await render()
    await user.click(await screen.findByRole('button', { name: 'End VRAT access of alice' }))
    const dialog = await screen.findByRole('dialog', { name: 'End VRAT access of alice' })
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'r')
    await user.click(within(dialog).getByRole('button', { name: 'End access' }))
    expect(await within(dialog).findByText('This entry has ended already. Reload to see it.')).toBeInTheDocument()
  })
})
