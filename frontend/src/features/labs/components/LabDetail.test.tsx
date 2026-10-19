import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeLab, makeMember, page, problem } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import type { Role } from '../schemas'
import { LabDetail } from './LabDetail'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const PARAMS = { limit: 25, offset: 0 }

function mockLab(role: Role) {
  mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', code: 'MYC', my_role: role }))
  mockApi(
    'get',
    '/api/v1/labs/{lab_public_id}/members/',
    page([
      makeMember({ username: 'alice', first_name: 'Alice', last_name: 'Adams', role: 'manager' }),
      makeMember({ username: 'bob', role: 'technician' }),
    ]),
  )
}

const render = () => renderWithProviders(<LabDetail labId={LAB_ID} params={PARAMS} onOffsetChange={vi.fn<(offset: number) => void>()} />)

describe('LabDetail', () => {
  it('leads a curator to the deposits, the depositors and the MTA templates', async () => {
    mockLab('curator')
    await render()
    const sections = await screen.findByRole('navigation', { name: 'Lab sections' })
    expect(within(sections).getAllByRole('link').map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
      ['Strains', `/labs/${LAB_ID}/strains`],
      ['Deposits', `/labs/${LAB_ID}/deposits`],
      ['Depositors', `/labs/${LAB_ID}/depositors`],
      ['MTA templates', `/labs/${LAB_ID}/mta-templates`],
    ])
  })

  it('shows the lab, my role and the members table', async () => {
    mockLab('viewer')
    await render()
    expect(screen.getByText('Loading the lab…')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { level: 1, name: 'Mycology' })).toBeInTheDocument()
    expect(screen.getByText('Code MYC. Your role: Viewer.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Strains' })).toHaveAttribute('href', `/labs/${LAB_ID}/strains`)
    // Depositors hold personal contacts: a viewer is not led to them.
    expect(screen.queryByRole('link', { name: 'Depositors' })).not.toBeInTheDocument()
    const table = await screen.findByRole('table', { name: 'Members' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows.map((row) => within(row).getAllByRole('cell').map((cell) => cell.textContent))).toEqual([
      ['alice', 'Alice Adams', 'Manager'],
      ['bob', '', 'Technician'],
    ])
  })

  // Below manager the server refuses every member change, so the screen offers none.
  it.each<Role>(['viewer', 'technician', 'curator'])('offers no manage controls to a %s', async (role) => {
    mockLab(role)
    await render()
    const table = await screen.findByRole('table', { name: 'Members' })
    expect(within(table).queryByRole('columnheader', { name: 'Actions' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Change role|Remove/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('form', { name: 'Add a member' })).not.toBeInTheDocument()
  })

  it('offers a manager every control, with every role up to their own', async () => {
    mockLab('manager')
    await render()
    expect(await screen.findByRole('button', { name: 'Change role of alice' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove bob' })).toBeInTheDocument()
    const form = screen.getByRole('form', { name: 'Add a member' })
    const options = within(form).getAllByRole('option').map((o) => o.textContent)
    expect(options).toEqual(['Viewer', 'Technician', 'Curator', 'Manager'])
  })

  it('says the lab is not found when I am not a member', async () => {
    mockApiError('get', '/api/v1/labs/{public_id}/', 404, problem(404, { code: 'not_found' }))
    mockApiError('get', '/api/v1/labs/{lab_public_id}/members/', 404, problem(404, { code: 'not_found' }))
    await render()
    expect(await screen.findByRole('heading', { name: 'Lab not found' })).toBeInTheDocument()
    expect(screen.getByText('The lab does not exist, or you are not a member of it.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('shows a failure of the lab with a retry that works', async () => {
    allowConsole(/API error 500/)
    mockApiError('get', '/api/v1/labs/{public_id}/', 500)
    await render()
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load the lab.')
    mockLab('viewer')
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('heading', { name: 'Mycology' })).toBeInTheDocument()
  })

  it('shows a failure of the members with a retry that works', async () => {
    allowConsole(/API error 500/)
    mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology' }))
    mockApiError('get', '/api/v1/labs/{lab_public_id}/members/', 500)
    await render()
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load the members.')
    mockApi('get', '/api/v1/labs/{lab_public_id}/members/', page([makeMember({ username: 'carol' })]))
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('cell', { name: 'carol' })).toBeInTheDocument()
  })

  it('says so when the lab has no members', async () => {
    mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID }))
    mockApi('get', '/api/v1/labs/{lab_public_id}/members/', page([]))
    await render()
    expect(await screen.findByText('This lab has no members yet.')).toBeInTheDocument()
  })
})
