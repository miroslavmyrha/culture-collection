import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { mockApi } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { FactorList } from './FactorList'

const KEY = { public_id: 'k1', name: 'Blue key', created_at: '2026-11-21T10:00:00Z', last_used_at: null }

describe('FactorList', () => {
  it('asks for a second factor before any change when it is not fresh', async () => {
    mockApi('get', '/api/v1/auth/factors/', { security_keys: [KEY], totp: true, recovery_codes_left: 9, fresh: false })
    await renderWithProviders(<FactorList />)
    expect(await screen.findByRole('list', { name: 'Second factors' })).toHaveTextContent('Security key: Blue key')
    expect(screen.getByText('Recovery codes left: 9')).toBeInTheDocument()
    expect(screen.getByText('To change them, confirm with your second factor first.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Remove/ })).not.toBeInTheDocument()
  })

  it('removes a factor once fresh, and keeps the last one', async () => {
    mockApi('get', '/api/v1/auth/factors/', { security_keys: [KEY], totp: true, recovery_codes_left: 10, fresh: true })
    const removed = mockApi('delete', '/api/v1/auth/factors/totp/remove/', undefined, { status: 204 })
    await renderWithProviders(<FactorList />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Remove the authenticator app' }))
    await vi.waitFor(() => expect(removed).toHaveLength(1))
  })

  it('offers no removal of the last factor', async () => {
    mockApi('get', '/api/v1/auth/factors/', { security_keys: [], totp: true, recovery_codes_left: 10, fresh: true })
    await renderWithProviders(<FactorList />)
    const remove = await screen.findByRole('button', { name: 'Remove the authenticator app' })
    expect(remove).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByText('Your last second factor stays. Add another one before removing it.')).toBeInTheDocument()
  })

  it('shows new recovery codes once', async () => {
    mockApi('get', '/api/v1/auth/factors/', { security_keys: [], totp: true, recovery_codes_left: 2, fresh: true })
    mockApi('post', '/api/v1/auth/factors/recovery-codes/', { recovery_codes: ['xxxxx-yyyyy'] }, { status: 201 })
    await renderWithProviders(<FactorList />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'New recovery codes' }))
    expect(await screen.findByRole('list', { name: 'Recovery codes' })).toHaveTextContent('xxxxx-yyyyy')
  })
})
