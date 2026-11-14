import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { makeLab, makeLabPermit, makeMe, makeMember, makeVratAccess, page } from '@/test/factories'
import { allowConsole } from '@/test/console'
import { mockApi, mockApiError, recordRequests } from '@/test/mockApi'
import { renderApp } from '@/test/render'

// The VRAT access list (#167, act 281/2002 Sb., § 14a(4)): its section on the lab page and its
// printable page with the lab's permit, both for managers only. Cross-feature: the page composes
// the permits feature's line.

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const VRAT = '/api/v1/labs/{lab_public_id}/vrat-access/'
const PERMITS = '/api/v1/labs/{lab_public_id}/permits/'
type Role = 'viewer' | 'technician' | 'curator' | 'manager'
const signedIn = (role: Role) => {
  mockApi('get', '/api/v1/auth/me/', makeMe())
  mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', code: 'MYC', my_role: role }))
}

const alice = makeVratAccess({ username: 'alice', first_name: 'Alice', last_name: 'Adams', granted_at: '2026-05-04T08:00:00Z', granted_by: 'carol', reason: 'works in the BSL-3 suite' })
const erased = makeVratAccess({
  username: 'erased-00000000-0000-4000-8000-0000000000e1',
  granted_at: '2026-01-10T08:00:00Z',
  ended_at: '2026-06-30T08:00:00Z',
  ended_by: null,
  end_reason: 'The account was erased.',
})

describe('the printable VRAT access list', () => {
  it('shows a manager the lab, the VRAT permit in force, every entry with from and until, and when it was printed', async () => {
    signedIn('manager')
    mockApi('get', VRAT, [alice, erased])
    mockApi('get', PERMITS, [
      makeLabPermit({ kind: 'cz_vrat', permit_reference: 'SÚJB/DEV/0001', valid_from: '2025-02-01', standing: 'valid', last_valid_day: null }),
      makeLabPermit({ kind: 'cz_vrat', permit_reference: 'SÚJB/DEV/OLD', standing: 'ended' }),
      makeLabPermit({ kind: 'quarantine_pest', issuer_label: 'ÚKZÚZ', permit_reference: 'UKZUZ/1', standing: 'valid' }),
    ])
    const print = vi.spyOn(window, 'print').mockImplementation(() => undefined)
    renderApp({ path: `/labs/${LAB_ID}/vrat-access` })
    const user = userEvent.setup()
    expect(await screen.findByRole('heading', { level: 1, name: 'VRAT access list of Mycology' })).toBeInTheDocument()
    await waitFor(() => expect(document.title).toBe('VRAT access list of Mycology | Culture collection'))
    const facts = document.querySelector('main dl') ?? document.body
    await waitFor(() => expect(facts).toHaveTextContent('LabMycology (MYC)PermitSÚJB SÚJB/DEV/0001, valid from 2025-02-01Rule'))
    expect(facts).toHaveTextContent(/Printed on\d{4}-\d\d-\d\d \d\d:\d\d/)
    const table = await screen.findByRole('table', { name: 'VRAT access list' })
    const rows = within(table)
      .getAllByRole('row')
      .slice(1)
      .map((row) => within(row).getAllByRole('cell').map((cell) => cell.textContent))
    expect(rows).toEqual([
      ['Alice Adamsalice', expect.stringMatching(/^2026-05-04/), 'has access', 'carol: works in the BSL-3 suite', ''],
      ['erased-00000000-0000-4000-8000-0000000000e1', expect.stringMatching(/^2026-01-10/), expect.stringMatching(/^2026-06-30/), 'alice: works with the VRAT strains', 'the system: The account was erased.'],
    ])
    expect(screen.getByText(/^1 person has access now\. Entries that ended stay on the list with their end\.$/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Print' }))
    expect(print).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('link', { name: 'Back to Mycology' })).toHaveAttribute('href', `/labs/${LAB_ID}`)
    print.mockRestore()
  })

  it('says when the lab holds no VRAT permit in force', async () => {
    signedIn('manager')
    mockApi('get', VRAT, [])
    mockApi('get', PERMITS, [makeLabPermit({ kind: 'cz_vrat', standing: 'expired' })])
    renderApp({ path: `/labs/${LAB_ID}/vrat-access` })
    expect(await screen.findByText('None in force on record')).toBeInTheDocument()
    expect(screen.getByText('Nobody has access now. Nobody was ever on the list.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it.each([
    ['two people with access', [alice, makeVratAccess({ username: 'bob' })], '2 people have access now. Entries that ended stay on the list with their end.'],
    ['every entry ended', [erased], 'Nobody has access now. Entries that ended stay on the list with their end.'],
  ])('counts who has access now: %s', async (_, entries, sentence) => {
    signedIn('manager')
    mockApi('get', VRAT, entries)
    mockApi('get', PERMITS, [])
    renderApp({ path: `/labs/${LAB_ID}/vrat-access` })
    expect(await screen.findByText(sentence)).toBeInTheDocument()
  })

  it('shows a failure to load the list with a retry', async () => {
    allowConsole(/API error 500/)
    signedIn('manager')
    mockApiError('get', VRAT, 500)
    mockApi('get', PERMITS, [])
    renderApp({ path: `/labs/${LAB_ID}/vrat-access` })
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load the VRAT access list.')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it.each<Role>(['viewer', 'technician', 'curator'])('tells a %s that only managers see it, and asks for nothing', async (role) => {
    signedIn(role)
    const asked = recordRequests('get', VRAT)
    const permits = recordRequests('get', PERMITS)
    renderApp({ path: `/labs/${LAB_ID}/vrat-access` })
    expect(await screen.findByText('Only managers see the VRAT access list.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Print' })).not.toBeInTheDocument()
    expect([asked, permits]).toEqual([[], []])
  })
})

describe('the VRAT access list on the lab page', () => {
  it('is there for a manager, under the members', async () => {
    signedIn('manager')
    mockApi('get', '/api/v1/labs/{lab_public_id}/members/', page([makeMember({ username: 'alice', role: 'manager' })]))
    mockApi('get', '/api/v1/labs/{lab_public_id}/location-grants/', [])
    mockApi('get', VRAT, [alice])
    renderApp({ path: `/labs/${LAB_ID}` })
    expect(await screen.findByRole('heading', { level: 2, name: 'VRAT access list' })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'End VRAT access of alice' })).toBeInTheDocument()
    expect(screen.getByRole('form', { name: 'Put a member on the VRAT access list' })).toBeInTheDocument()
  })

  it.each<Role>(['viewer', 'technician', 'curator'])('is absent for a %s, and never asked for', async (role) => {
    signedIn(role)
    mockApi('get', '/api/v1/labs/{lab_public_id}/members/', page([makeMember({ username: 'alice', role: 'manager' })]))
    const asked = recordRequests('get', VRAT)
    renderApp({ path: `/labs/${LAB_ID}` })
    expect(await screen.findByRole('table', { name: 'Members' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'VRAT access list' })).not.toBeInTheDocument()
    expect(screen.queryByRole('form', { name: 'Put a member on the VRAT access list' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Print the VRAT access list' })).not.toBeInTheDocument()
    expect(asked).toHaveLength(0)
  })
})
