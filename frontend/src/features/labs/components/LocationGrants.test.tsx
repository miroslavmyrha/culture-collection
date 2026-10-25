import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeLocationGrant, makeMember, page, problem, validationProblem } from '@/test/factories'
import { mockApi, mockApiError, recordRequests } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { ROLES } from '../schemas'
import { MemberTable } from './MemberTable'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const PARAMS = { limit: 25, offset: 0 }
const GRANTS = '/api/v1/labs/{lab_public_id}/location-grants/'

const alice = makeMember({ username: 'alice', role: 'manager' })
const bob = makeMember({ username: 'bob', role: 'technician' })
const held = makeLocationGrant({ member: alice.public_id, username: 'alice' })

async function render(grantable = [...ROLES]) {
  mockApi('get', '/api/v1/labs/{lab_public_id}/members/', page([alice, bob]))
  const view = await renderWithProviders(
    <MemberTable labId={LAB_ID} labName="Mycology" grantable={grantable} params={PARAMS} onOffsetChange={vi.fn<(offset: number) => void>()} />,
  )
  await screen.findByRole('table', { name: 'Members' })
  return { ...view, user: userEvent.setup() }
}

const cellOf = (username: string) => {
  const row = screen.getByRole('row', { name: new RegExp(username) })
  return within(row).getAllByRole('cell')[3]
}

describe('who may see regulated locations (ADR 0009)', { timeout: 20_000 }, () => {
  it('shows a manager who holds the grant and offers to grant or revoke it', async () => {
    mockApi('get', GRANTS, [held])
    await render()
    await waitFor(() => expect(cellOf('alice')).toHaveTextContent('May see'))
    expect(cellOf('bob')).toHaveTextContent('Hidden')
    expect(screen.getByRole('button', { name: 'Revoke regulated locations for alice' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Grant regulated locations for bob' })).toBeInTheDocument()
  })

  it('neither shows nor asks for the grants of a member who may not manage', async () => {
    const asked = recordRequests('get', GRANTS)
    await render([])
    expect(screen.queryByRole('columnheader', { name: 'Regulated locations' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /regulated locations/ })).not.toBeInTheDocument()
    expect(asked).toHaveLength(0)
  })

  it('grants with a reason, asked for before any request, and refreshes the column', async () => {
    const lists = mockApi('get', GRANTS, [])
    const calls = mockApi('post', GRANTS, makeLocationGrant({ member: bob.public_id, username: 'bob' }))
    const { user } = await render()
    const trigger = await screen.findByRole('button', { name: 'Grant regulated locations for bob' })
    await user.click(trigger)
    const dialog = await screen.findByRole('dialog', { name: 'Let bob see regulated locations' })
    expect(dialog).toHaveAccessibleDescription(/one vial at a time\. Every reveal is recorded\./)
    const reason = within(dialog).getByRole('textbox', { name: 'Reason' })
    expect(reason).toHaveFocus()
    await user.click(within(dialog).getByRole('button', { name: 'Grant' }))
    expect(reason).toHaveAccessibleDescription('Stored for good with the change. Name no person. Say why')
    expect(calls).toHaveLength(0)
    await user.type(reason, ' keeps the register ')
    mockApi('get', GRANTS, [makeLocationGrant({ member: bob.public_id, username: 'bob' })])
    await user.click(within(dialog).getByRole('button', { name: 'Grant' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ member: bob.public_id, reason: 'keeps the register' })
    expect(calls[0]?.headers.get('X-CSRFToken')).toBe('test-token')
    await waitFor(() => expect(cellOf('bob')).toHaveTextContent('May see'))
    expect(lists.length).toBeGreaterThan(0)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Revoke regulated locations for bob' })).toHaveFocus())
  })

  it('revokes with a reason', async () => {
    mockApi('get', GRANTS, [held])
    const calls = mockApi('post', '/api/v1/labs/{lab_public_id}/location-grants/{public_id}/revoke/', undefined)
    const { user } = await render()
    await user.click(await screen.findByRole('button', { name: 'Revoke regulated locations for alice' }))
    const dialog = await screen.findByRole('dialog', { name: 'Stop alice seeing regulated locations' })
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'moved to another project')
    mockApi('get', GRANTS, [])
    await user.click(within(dialog).getByRole('button', { name: 'Revoke' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.url.pathname).toBe(`/api/v1/labs/${LAB_ID}/location-grants/${held.public_id}/revoke/`)
    expect(calls[0]?.body).toEqual({ reason: 'moved to another project' })
    await waitFor(() => expect(cellOf('alice')).toHaveTextContent('Hidden'))
  })

  it('says inside the dialog when someone granted it meanwhile', async () => {
    mockApi('get', GRANTS, [])
    mockApiError('post', GRANTS, 400, { ...problem(400, { code: 'already_granted' }), errors: [{ attr: 'member', code: 'already_granted', detail: 'x' }] })
    const { user } = await render()
    await user.click(await screen.findByRole('button', { name: 'Grant regulated locations for bob' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'register')
    await user.click(within(dialog).getByRole('button', { name: 'Grant' }))
    expect(await within(dialog).findByText('This member may see regulated locations already. Reload to see it.')).toBeInTheDocument()
  })

  it('shows a 400 on a field the dialog does not have', async () => {
    mockApi('get', GRANTS, [])
    mockApiError('post', GRANTS, 400, validationProblem([{ attr: 'member', code: 'inactive', detail: 'This member is not active.' }]))
    const { user } = await render()
    await user.click(await screen.findByRole('button', { name: 'Grant regulated locations for bob' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'register')
    await user.click(within(dialog).getByRole('button', { name: 'Grant' }))
    expect(await within(dialog).findByText('This member is not active.')).toBeInTheDocument()
  })

  it('says when the grants could not be loaded, and offers no grant button then', async () => {
    allowConsole(/API error 500/)
    mockApiError('get', GRANTS, 500)
    await render()
    await waitFor(() => expect(cellOf('bob')).toHaveTextContent('Could not load'))
    expect(screen.queryByRole('button', { name: /regulated locations/ })).not.toBeInTheDocument()
  })
})
