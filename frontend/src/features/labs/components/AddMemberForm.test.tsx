import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeMember, problem, validationProblem } from '@/test/factories'
import { mockApi, mockApiError, recordRequests } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { labKeys } from '../api/keys'
import { type Role, ROLES } from '../schemas'
import { AddMemberForm } from './AddMemberForm'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const PATH = '/api/v1/labs/{lab_public_id}/members/'

async function setup(roles: Role[] = [...ROLES]) {
  const view = await renderWithProviders(<AddMemberForm labId={LAB_ID} roles={roles} />)
  const user = userEvent.setup()
  const fill = async (username: string, role: Role = 'curator') => {
    await user.type(screen.getByRole('textbox', { name: 'Username' }), username)
    await user.selectOptions(screen.getByRole('combobox', { name: 'Role' }), role)
    await user.click(screen.getByRole('button', { name: 'Add member' }))
  }
  return { ...view, user, fill }
}

describe('AddMemberForm', () => {
  it('sends the username and role with the CSRF token, says who was added and refreshes the lab', async () => {
    const calls = mockApi('post', PATH, makeMember({ username: 'sam', role: 'curator' }))
    const { client, fill } = await setup()
    client.setQueryData(labKeys.memberList(LAB_ID, { limit: 25, offset: 0 }), { count: 0, next: null, previous: null, results: [] })
    await fill('  sam ')
    expect(await screen.findByText('Added sam.')).toBeInTheDocument()
    expect(calls).toHaveLength(1)
    expect(calls[0]?.url.pathname).toBe(`/api/v1/labs/${LAB_ID}/members/`)
    expect(calls[0]?.body).toEqual({ username: 'sam', role: 'curator' })
    expect(calls[0]?.headers.get('X-CSRFToken')).toBe('test-token')
    expect(client.getQueryState(labKeys.memberList(LAB_ID, { limit: 25, offset: 0 }))?.isInvalidated).toBe(true)
    expect(screen.getByRole('textbox', { name: 'Username' })).toHaveValue('') // reset for the next one
  })

  it('offers only the roles it is given', async () => {
    await setup(['viewer', 'technician'])
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['Viewer', 'Technician'])
  })

  it('refuses an empty username without a request', async () => {
    const calls = recordRequests('post', PATH)
    const { user } = await setup()
    await user.click(screen.getByRole('button', { name: 'Add member' }))
    const field = screen.getByRole('textbox', { name: 'Username' })
    expect(field).toHaveAccessibleDescription('An existing, active user Enter a username')
    expect(field).toHaveFocus()
    expect(calls).toHaveLength(0)
  })

  it.each([
    ['does_not_exist', 'Invalid user.'],
    ['already_member', 'This user is already a member of the lab.'],
  ])('puts the server error %s on the username field and focuses it', async (code, detail) => {
    mockApiError('post', PATH, 400, validationProblem([{ attr: 'username', code, detail }]))
    const { fill } = await setup()
    await fill('someone')
    const field = screen.getByRole('textbox', { name: 'Username' })
    await waitFor(() => expect(field).toHaveAttribute('aria-invalid', 'true'))
    expect(field).toHaveAccessibleDescription(`An existing, active user ${detail}`)
    expect(field).toHaveFocus()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument() // described, not announced
  })

  it('clears the field error when the username is edited', async () => {
    mockApiError('post', PATH, 400, validationProblem([{ attr: 'username', code: 'does_not_exist', detail: 'Invalid user.' }]))
    const { fill, user } = await setup()
    await fill('nobody')
    const field = screen.getByRole('textbox', { name: 'Username' })
    await waitFor(() => expect(field).toHaveAttribute('aria-invalid', 'true'))
    await user.type(field, 'x')
    expect(field).toHaveAttribute('aria-invalid', 'false')
    expect(field).toHaveAccessibleDescription('An existing, active user')
  })

  it('shows a non-field error once', async () => {
    mockApiError('post', PATH, 400, validationProblem([{ attr: null, code: 'invalid', detail: 'Something about the request.' }]))
    const { fill } = await setup()
    await fill('sam')
    expect(await screen.findAllByRole('alert')).toHaveLength(1)
    expect(screen.getByRole('alert')).toHaveTextContent('Something about the request.')
  })

  it.each([
    [403, 'You do not have permission to do that.'],
    [500, 'The server failed. Try again in a moment.'],
  ])('shows a safe message for %i, never the server text', async (status, message) => {
    allowConsole(/API error 500/)
    mockApiError('post', PATH, status, problem(status, { detail: 'internal detail' }))
    const { fill } = await setup()
    await fill('sam')
    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    expect(screen.queryByText(/internal detail/)).not.toBeInTheDocument()
  })
})
