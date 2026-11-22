import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { makeMember, problem } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { EnrolmentCodeDialog } from './EnrolmentCodeDialog'

const member = makeMember({ public_id: 'm1', username: 'newcomer' })
const render = () => renderWithProviders(<EnrolmentCodeDialog labId="lab" member={member} open onClose={vi.fn<() => void>()} onExited={vi.fn<() => void>()} />)

describe('EnrolmentCodeDialog', () => {
  it('issues a code with a reason and shows it once', async () => {
    const issued = mockApi('post', '/api/v1/auth/enrolment-codes/', { code: 'abcde-fghjk', username: 'newcomer', valid_hours: 24 }, { status: 201 })
    await render()
    const user = userEvent.setup()
    await user.type(screen.getByRole('textbox', { name: 'Reason' }), 'Started today.')
    await user.click(screen.getByRole('button', { name: 'Issue the code' }))
    expect(await screen.findByText('abcde-fghjk')).toBeInTheDocument()
    expect(screen.getByText('Valid for 24 hours, once.')).toBeInTheDocument()
    expect(issued[0]?.body).toEqual({ member: 'm1', reason: 'Started today.' })
  })

  it('says why the server refused', async () => {
    mockApiError('post', '/api/v1/auth/enrolment-codes/', 422, problem(422, { code: 'reset_own_factor', detail: 'Not for your own account.' }))
    await render()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Issue the code' }))
    expect(await screen.findByText('Not for your own account.')).toBeInTheDocument()
  })
})
