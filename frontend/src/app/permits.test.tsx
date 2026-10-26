import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { makeLab, makeMe, makeLabPermit, problem } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { renderApp } from '@/test/render'

// The permits page of a lab (#82): the lab gate, the role rule and the list together.

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const PERMITS = '/api/v1/labs/{lab_public_id}/permits/'
const signedIn = (role: 'viewer' | 'technician' | 'curator' | 'manager') => {
  mockApi('get', '/api/v1/auth/me/', makeMe())
  mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: role }))
}

describe('the permits page', { timeout: 15_000 }, () => {
  it('shows a manager the permits and says that staff change them in the Django admin', async () => {
    signedIn('manager')
    mockApi('get', PERMITS, [makeLabPermit({ permit_reference: 'DEV/VRAT/1', standing: 'expires_soon', expires_on: '2026-11-05', last_valid_day: '2026-11-05', days_left: 10 })])
    renderApp({ path: `/labs/${LAB_ID}/permits` })
    expect(await screen.findByRole('heading', { level: 1, name: 'Permits of Mycology' }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByText(/This list is read only: staff record a permit and its end in the Django admin\./)).toBeInTheDocument()
    expect(await screen.findByRole('table', { name: 'Permits' })).toHaveTextContent('SÚJB DEV/VRAT/1')
    expect(screen.getByText('1 permit expires soon.')).toBeInTheDocument()
  })

  it.each(['viewer', 'technician', 'curator'] as const)('tells a %s that only managers see them, and shows no list', async (role) => {
    signedIn(role)
    mockApiError('get', PERMITS, 403, problem(403))
    renderApp({ path: `/labs/${LAB_ID}/permits` })
    expect(await screen.findByText("Only managers see the lab's permits.", {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByText(/Could not load/)).not.toBeInTheDocument()
  })
})
