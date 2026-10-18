import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { makeMember, page, problem } from '@/test/factories'
import { mockApi, mockApiError, recordRequests } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { ROLES } from '../schemas'
import { MemberTable } from './MemberTable'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const PARAMS = { limit: 25, offset: 0 }
const DETAIL = '/api/v1/labs/{lab_public_id}/members/{public_id}/'

async function setup() {
  const bob = makeMember({ username: 'bob', role: 'technician' })
  const lists = mockApi('get', '/api/v1/labs/{lab_public_id}/members/', page([makeMember({ username: 'alice', role: 'manager' }), bob]))
  const view = await renderWithProviders(
    <MemberTable labId={LAB_ID} labName="Mycology" grantable={[...ROLES]} params={PARAMS} onOffsetChange={vi.fn<(offset: number) => void>()} />,
  )
  await screen.findByRole('table', { name: 'Members' })
  return { ...view, bob, lists, user: userEvent.setup() }
}

describe('changing a role', () => {
  it('sends the new role, closes and refreshes the lab', async () => {
    const { bob, user, lists } = await setup()
    const calls = mockApi('patch', DETAIL, { ...bob, role: 'curator' })
    await user.click(screen.getByRole('button', { name: 'Change role of bob' }))
    const dialog = screen.getByRole('dialog', { name: 'Change the role of bob' })
    expect(within(dialog).getByRole('combobox', { name: 'Role' })).toHaveValue('technician')
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Role' }), 'curator')
    await user.click(within(dialog).getByRole('button', { name: 'Save role' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(calls[0]?.url.pathname).toBe(`/api/v1/labs/${LAB_ID}/members/${bob.public_id}/`)
    expect(calls[0]?.body).toEqual({ role: 'curator' })
    expect(calls[0]?.headers.get('X-CSRFToken')).toBe('test-token')
    expect(lists).toHaveLength(2) // the list on screen was fetched again
  })

  it('explains why the last manager stays, and keeps the dialog open', async () => {
    const { user } = await setup()
    mockApiError('patch', DETAIL, 422, problem(422, { code: 'last_manager', detail: 'server text' }))
    await user.click(screen.getByRole('button', { name: 'Change role of alice' }))
    const dialog = screen.getByRole('dialog', { name: 'Change the role of alice' })
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Role' }), 'viewer')
    await user.click(within(dialog).getByRole('button', { name: 'Save role' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('A lab needs at least one active manager. Make another member manager first.')
    expect(screen.queryByText('server text')).not.toBeInTheDocument()
  })

  it('sends nothing on cancel', async () => {
    const { user } = await setup()
    const calls = recordRequests('patch', DETAIL)
    await user.click(screen.getByRole('button', { name: 'Change role of bob' }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(calls).toHaveLength(0)
  })
})

describe('removing a member', () => {
  it('asks first, with the focus on Cancel, and sends nothing on cancel', async () => {
    const { user } = await setup()
    const calls = recordRequests('delete', DETAIL)
    await user.click(screen.getByRole('button', { name: 'Remove bob' }))
    const dialog = screen.getByRole('dialog', { name: 'Remove bob?' })
    expect(dialog).toHaveTextContent('bob leaves Mycology and loses access to it at once.')
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(calls).toHaveLength(0)
  })

  it('removes after the confirmation and refreshes the members', async () => {
    const { bob, user, lists } = await setup()
    const calls = mockApi('delete', DETAIL, undefined)
    await user.click(screen.getByRole('button', { name: 'Remove bob' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(calls).toHaveLength(1)
    expect(calls[0]?.url.pathname).toBe(`/api/v1/labs/${LAB_ID}/members/${bob.public_id}/`)
    expect(lists).toHaveLength(2) // the list on screen was fetched again
  })

  it('explains why the last manager cannot be removed', async () => {
    const { user } = await setup()
    mockApiError('delete', DETAIL, 422, problem(422, { code: 'last_manager' }))
    await user.click(screen.getByRole('button', { name: 'Remove alice' }))
    const dialog = screen.getByRole('dialog', { name: 'Remove alice?' })
    await user.click(within(dialog).getByRole('button', { name: 'Remove' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('A lab needs at least one active manager.')
  })
})
