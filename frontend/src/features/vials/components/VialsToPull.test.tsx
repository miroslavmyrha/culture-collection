import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeVial } from '@/test/factories'
import { holdApi, mockApi, mockApiError, recordRequests } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { VialsToPull } from './VialsToPull'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const REQUEST_ID = '00000000-0000-4000-8000-0000000000a1'
const VIALS = '/api/v1/labs/{lab_public_id}/requests/{public_id}/vials/'
const REVEAL = '/api/v1/labs/{lab_public_id}/vials/{public_id}/reveal-location/'

const at = (path: string[], row: number, col: number, label: string) => ({
  box: '00000000-0000-4000-8000-000000000b01',
  box_name: path[path.length - 1] ?? '',
  path,
  row,
  col,
  label,
})
// As the server sends them (#143): the walk, then the masked vials, then the one in no box.
const first = makeVial({ label: 'MYC 42 / 1 / 3', status: 'reserved', placed: true, location: at(['Freezer A', 'Rack 1', 'Box 1'], 1, 3, 'A3') })
const second = makeVial({ label: 'MYC 42 / 1 / 2', status: 'reserved', placed: true, location: at(['Freezer B', 'Box B'], 1, 1, 'A1') })
const masked = makeVial({ label: 'MYC 7 / 1 / 1', status: 'reserved', placed: true, location_masked: true })
const loose = makeVial({ label: 'MYC 42 / 2 / 1', status: 'reserved' })

const render = () => renderWithProviders(<VialsToPull labId={LAB_ID} requestId={REQUEST_ID} />)
const rows = () => within(screen.getByRole('table', { name: 'Vials to pull' })).getAllByRole('row').slice(1)
const cells = (row: HTMLElement | undefined) => (row ? within(row).getAllByRole('cell').map((c) => c.textContent) : [])

describe('the vials to pull for a request', { timeout: 20_000 }, () => {
  it('lists the reserved vials in the order the server walks them, each with its place', async () => {
    const asked = mockApi('get', VIALS, [first, second, masked, loose])
    await render()
    expect(screen.getByText('Loading the vials to pull…')).toBeInTheDocument()
    await screen.findByRole('table', { name: 'Vials to pull' })
    expect(asked).toHaveLength(1)
    expect(rows().map(cells)).toEqual([
      ['1', 'MYC 42 / 1 / 3', 'Freezer A / Rack 1 / Box 1, A3'],
      ['2', 'MYC 42 / 1 / 2', 'Freezer B / Box B, A1'],
      ['3', 'MYC 7 / 1 / 1', 'Hidden: regulated strain'],
      ['4', 'MYC 42 / 2 / 1', 'Not placed'],
    ])
    // The table may scroll sideways at 320 px: a named region a keyboard reaches.
    expect(screen.getByRole('region', { name: 'Vials to pull table' })).toHaveAttribute('tabindex', '0')
    expect(screen.getByText(/Vials of a regulated strain come after the others: their place is hidden/)).toBeInTheDocument()
  })

  it('says nothing of hidden places when no vial is masked', async () => {
    mockApi('get', VIALS, [first, loose])
    await render()
    await screen.findByRole('table', { name: 'Vials to pull' })
    expect(screen.queryByText(/regulated strain/)).not.toBeInTheDocument()
  })

  it('hides a regulated place without a way to reveal it for a reader without the grant', async () => {
    mockApi('get', VIALS, [masked])
    const reveals = recordRequests('post', REVEAL)
    await render()
    await screen.findByRole('table', { name: 'Vials to pull' })
    expect(cells(rows()[0])[2]).toBe('Hidden: regulated strain')
    expect(screen.queryByRole('button', { name: /Reveal/ })).not.toBeInTheDocument()
    expect(reveals).toHaveLength(0)
  })

  it('reveals a regulated place for a holder, each time anew, keeps the focus, and hides it again', async () => {
    mockApi('get', VIALS, [first, { ...masked, can_reveal: true }])
    const held = holdApi('post', REVEAL)
    await render()
    const user = userEvent.setup()
    const button = await screen.findByRole('button', { name: 'Reveal the location of vial MYC 7 / 1 / 1' })
    await user.click(button)
    expect(button).toHaveAttribute('aria-disabled', 'true')
    await user.click(button) // pending: no second request
    expect(held.calls).toHaveLength(1)
    expect(held.calls[0]?.url.pathname).toContain(`/labs/${LAB_ID}/vials/${masked.public_id}/reveal-location/`)
    held.release(200, { location: at(['Freezer A', 'Rack 1', 'Box R'], 1, 2, 'A2') })
    expect(await screen.findByText('Freezer A / Rack 1 / Box R, A2')).toHaveAttribute('aria-live', 'polite')
    expect(button).toHaveFocus()
    await user.click(button)
    expect(screen.queryByText(/Box R/)).not.toBeInTheDocument()
    expect(cells(rows()[1])[2]).toBe('Hidden: regulated strainReveal location')
    expect(button).toHaveFocus()
    await user.click(button)
    await screen.findByText('Freezer A / Rack 1 / Box R, A2')
    expect(held.calls).toHaveLength(2) // never from a cache
  })

  it('says why a reveal was refused, and shows no place', async () => {
    mockApi('get', VIALS, [{ ...masked, can_reveal: true }])
    mockApiError('post', REVEAL, 403, { type: 'about:blank', title: 'Forbidden', status: 403, detail: 'No grant.', code: 'location_grant_required' })
    await render()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Reveal the location of vial MYC 7 / 1 / 1' }))
    await waitFor(() => expect(cells(rows()[0])[2]).not.toContain('Hidden'))
    expect(cells(rows()[0])[2]).not.toMatch(/Freezer|Box/)
  })

  it('says when no vial is reserved', async () => {
    mockApi('get', VIALS, [])
    await render()
    expect(await screen.findByText('No vial is reserved for this request now.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('shows the error with a retry that loads the list', async () => {
    allowConsole(/API error 500/)
    mockApiError('get', VIALS, 500)
    await render()
    const user = userEvent.setup()
    const retry = await screen.findByRole('button', { name: 'Try again' })
    expect(screen.getByText(/Could not load the vials to pull/)).toBeInTheDocument()
    mockApi('get', VIALS, [first])
    await user.click(retry)
    await screen.findByRole('table', { name: 'Vials to pull' })
    expect(cells(rows()[0])).toEqual(['1', 'MYC 42 / 1 / 3', 'Freezer A / Rack 1 / Box 1, A3'])
  })
})
