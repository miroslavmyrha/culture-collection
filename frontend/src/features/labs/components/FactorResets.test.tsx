import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { mockApi } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { FactorResets } from './FactorResets'

const LAB = '00000000-0000-4000-8000-000000000001'
const RESET = { public_id: 'r1', member: 'm1', username: 'lost-key', proposed_by: 'first-manager', proposed_at: '2026-11-21T10:00:00Z', reason: 'Lost the phone.' }
const MEMBERS = { count: 1, next: null, previous: null, results: [{ public_id: 'm1', username: 'lost-key', first_name: '', last_name: '', role: 'technician' as const, created_at: '2026-11-01T10:00:00Z' }] }

describe('FactorResets', () => {
  it('lets another manager confirm, with a reason', async () => {
    mockApi('get', '/api/v1/auth/factor-resets/', [{ ...RESET, may_confirm: true }])
    mockApi('get', '/api/v1/labs/{lab_public_id}/members/', MEMBERS)
    const confirm = mockApi('post', '/api/v1/auth/factor-resets/{public_id}/confirm/', { ...RESET, may_confirm: true, enrolment_code: 'hand1-over2' })
    await renderWithProviders(<FactorResets labId={LAB} />)
    const user = userEvent.setup()
    const reset = await screen.findByRole('article', { name: 'Reset for lost-key' })
    expect(reset).toHaveTextContent('proposed by first-manager. Lost the phone.')
    await user.type(screen.getByRole('textbox', { name: 'Reason (reset for lost-key)' }), 'Checked in person.')
    await user.click(screen.getByRole('button', { name: 'Confirm the reset' }))
    await vi.waitFor(() => expect(confirm[0]?.body).toEqual({ reason: 'Checked in person.' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Hand lost-key this enrolment code in person, it is not shown again: hand1-over2')
  })

  it('offers the proposer no confirmation', async () => {
    mockApi('get', '/api/v1/auth/factor-resets/', [{ ...RESET, may_confirm: false }])
    mockApi('get', '/api/v1/labs/{lab_public_id}/members/', MEMBERS)
    await renderWithProviders(<FactorResets labId={LAB} />)
    expect(await screen.findByText('Another manager confirms it.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirm the reset' })).not.toBeInTheDocument()
  })

  it('proposes a reset for a member', async () => {
    mockApi('get', '/api/v1/auth/factor-resets/', [])
    mockApi('get', '/api/v1/labs/{lab_public_id}/members/', MEMBERS)
    const proposed = mockApi('post', '/api/v1/auth/factor-resets/propose/', { ...RESET, may_confirm: false }, { status: 201 })
    await renderWithProviders(<FactorResets labId={LAB} />)
    const user = userEvent.setup()
    expect(await screen.findByText('No reset waits.')).toBeInTheDocument()
    await user.type(await screen.findByRole('textbox', { name: 'Username of the member' }), 'lost-key')
    await user.type(screen.getByRole('textbox', { name: 'Reason' }), 'Lost the phone.')
    await user.click(screen.getByRole('button', { name: 'Propose a reset' }))
    await vi.waitFor(() => expect(proposed[0]?.body).toEqual({ member: 'm1', reason: 'Lost the phone.' }))
  })

  it('says so when no member has the username', async () => {
    mockApi('get', '/api/v1/auth/factor-resets/', [])
    mockApi('get', '/api/v1/labs/{lab_public_id}/members/', MEMBERS)
    await renderWithProviders(<FactorResets labId={LAB} />)
    const user = userEvent.setup()
    await user.type(await screen.findByRole('textbox', { name: 'Username of the member' }), 'nobody')
    await user.click(screen.getByRole('button', { name: 'Propose a reset' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('No member of this lab has that username.')
  })
})
