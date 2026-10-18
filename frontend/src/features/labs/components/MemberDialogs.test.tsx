import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { makeMember, page, problem } from '@/test/factories'
import { holdApi, mockApi, mockApiError, recordRequests } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { ROLES } from '../schemas'
import { MemberTable } from './MemberTable'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const PARAMS = { limit: 25, offset: 0 }
const DETAIL = '/api/v1/labs/{lab_public_id}/members/{public_id}/'

/** The container around the paper: a click there is a click on the backdrop for MUI. */
function backdropOf(dialog: HTMLElement) {
  const container = dialog.parentElement
  if (!container) throw new Error('the dialog has no container')
  return container
}

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
    const dialog = screen.getByRole('dialog', { name: 'Change the role of bob', description: 'The new role applies with their next request.' })
    expect(within(dialog).getByRole('combobox', { name: 'Role' })).toHaveValue('technician')
    expect(within(dialog).getByRole('combobox', { name: 'Role' })).toHaveFocus()
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

  it('stays open through Escape, the backdrop and Cancel while the change runs, and shows its failure inside', async () => {
    const { user } = await setup()
    const change = holdApi('patch', DETAIL)
    await user.click(screen.getByRole('button', { name: 'Change role of bob' }))
    const dialog = screen.getByRole('dialog', { name: 'Change the role of bob' })
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Role' }), 'curator')
    const save = within(dialog).getByRole('button', { name: 'Save role' })
    await user.click(save)
    await waitFor(() => expect(save).toHaveAttribute('aria-busy', 'true'))
    await user.keyboard('{Escape}')
    await user.click(backdropOf(dialog))
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    await user.click(save)
    expect(screen.getByRole('dialog', { name: 'Change the role of bob' })).toBe(dialog)
    change.release(500)
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('The server failed. Try again in a moment.')
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(change.calls).toHaveLength(1)
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
    const dialog = screen.getByRole('alertdialog', { name: 'Remove bob?', description: 'bob leaves Mycology and loses access to it at once.' })
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(calls).toHaveLength(0)
  })

  it('removes after the confirmation and refreshes the members', async () => {
    const { bob, user, lists } = await setup()
    const calls = mockApi('delete', DETAIL, undefined)
    await user.click(screen.getByRole('button', { name: 'Remove bob' }))
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(calls).toHaveLength(1)
    expect(calls[0]?.url.pathname).toBe(`/api/v1/labs/${LAB_ID}/members/${bob.public_id}/`)
    expect(lists).toHaveLength(2) // the list on screen was fetched again
  })

  it('explains why the last manager cannot be removed', async () => {
    const { user } = await setup()
    mockApiError('delete', DETAIL, 422, problem(422, { code: 'last_manager' }))
    await user.click(screen.getByRole('button', { name: 'Remove alice' }))
    const dialog = screen.getByRole('alertdialog', { name: 'Remove alice?' })
    await user.click(within(dialog).getByRole('button', { name: 'Remove' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('A lab needs at least one active manager.')
  })

  // Closing the dialog mid-request would unmount its mutation, and with meta.handlesError the
  // global notice stays quiet too: a failed removal would be shown nowhere.
  it('stays open through Escape, the backdrop and Cancel while the removal runs, and shows its failure inside', async () => {
    const { user } = await setup()
    const removal = holdApi('delete', DETAIL)
    await user.click(screen.getByRole('button', { name: 'Remove bob' }))
    const dialog = screen.getByRole('alertdialog', { name: 'Remove bob?' })
    const confirm = within(dialog).getByRole('button', { name: 'Remove' })
    await user.click(confirm)
    await waitFor(() => expect(confirm).toHaveAttribute('aria-busy', 'true'))
    await user.keyboard('{Escape}')
    await user.click(backdropOf(dialog))
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    await user.click(confirm)
    expect(screen.getByRole('alertdialog', { name: 'Remove bob?' })).toBe(dialog)
    expect(confirm).toHaveFocus() // nothing dropped the focus to the body

    removal.release(500)
    const alert = await within(dialog).findByRole('alert')
    expect(alert).toHaveTextContent('The server failed. Try again in a moment.')
    expect(screen.getAllByRole('alert')).toEqual([alert]) // no second, global message
    expect(dialog).toHaveAccessibleDescription('bob leaves Mycology and loses access to it at once. The server failed. Try again in a moment.')
    expect(removal.calls).toHaveLength(1)
    // Done: Cancel closes again.
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
  })

  it('closes when the removal it waited for succeeds', async () => {
    const { user } = await setup()
    const removal = holdApi('delete', DETAIL)
    await user.click(screen.getByRole('button', { name: 'Remove bob' }))
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Remove' }))
    await user.keyboard('{Escape}')
    removal.release(204)
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(removal.calls).toHaveLength(1)
  })
})
