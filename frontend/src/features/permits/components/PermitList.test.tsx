import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeLabPermit } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { PermitList } from './PermitList'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const LIST = '/api/v1/labs/{lab_public_id}/permits/'

const soon = makeLabPermit({ permit_reference: 'DEV/VRAT/1', standing: 'expires_soon', expires_on: '2026-11-05', last_valid_day: '2026-11-05', days_left: 12 })
const valid = makeLabPermit({
  kind: 'quarantine_pest',
  kind_label: 'Permit to hold quarantine pests',
  issuer: 'ukzuz',
  issuer_label: 'ÚKZÚZ',
  permit_reference: 'DEV/QP/2',
})
const later = makeLabPermit({ permit_reference: 'DEV/VRAT/3', standing: 'not_yet_valid', valid_from: '2027-01-01' })
const expired = makeLabPermit({ permit_reference: 'DEV/VRAT/4', standing: 'expired', expires_on: '2026-03-31', last_valid_day: '2026-03-31' })
const ended = makeLabPermit({ permit_reference: 'DEV/VRAT/5', standing: 'ended', ended_on: '2025-06-01', end_reason: 'Revoked by decision DEV/9', last_valid_day: '2025-05-31' })

const toneOf = (reference: string) => rowOf(reference).querySelector('[data-tone]')?.getAttribute('data-tone') ?? null

function rowOf(reference: string) {
  const row = screen.getByText(reference, { exact: false }).closest('tr')
  if (!row) throw new Error(`no row for ${reference}`)
  return row
}

describe('PermitList', () => {
  it('lists the permits in the order the server gives, each with its status in words', async () => {
    mockApi('get', LIST, [soon, valid, later, expired, ended])
    await renderWithProviders(<PermitList labId={LAB_ID} />)
    const table = await screen.findByRole('table', { name: 'Permits' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows.map((row) => within(row).getAllByRole('cell')[1]?.textContent)).toEqual([
      'SÚJB DEV/VRAT/1',
      'ÚKZÚZ DEV/QP/2',
      'SÚJB DEV/VRAT/3',
      'SÚJB DEV/VRAT/4',
      'SÚJB DEV/VRAT/5',
    ])
    expect(rowOf('DEV/VRAT/1')).toHaveTextContent('Permit to handle highly risky agents (VRAT)')
    expect(rowOf('DEV/VRAT/1')).toHaveTextContent('Expires soonLast valid day 2026-11-05, in 12 days')
    expect(rowOf('DEV/QP/2')).toHaveTextContent('Permit to hold quarantine pests')
    expect(rowOf('DEV/QP/2')).toHaveTextContent('ValidNo expiry stated')
    expect(rowOf('DEV/VRAT/3')).toHaveTextContent('Not valid yetValid from 2027-01-01')
    expect(rowOf('DEV/VRAT/4')).toHaveTextContent('ExpiredLast valid day 2026-03-31')
    expect(rowOf('DEV/VRAT/5')).toHaveTextContent('EndedEnded on 2025-06-01: Revoked by decision DEV/9')
    expect(screen.getByText('1 permit expires soon.')).toBeInTheDocument()
  })

  it('marks what expires soon, what is not valid yet, expired and ended with a tone; a valid one stays plain', async () => {
    mockApi('get', LIST, [soon, valid, later, expired, ended])
    await renderWithProviders(<PermitList labId={LAB_ID} />)
    await screen.findByRole('table', { name: 'Permits' })
    expect(toneOf('DEV/VRAT/1')).toBe('warning')
    expect(toneOf('DEV/QP/2')).toBeNull()
    expect(toneOf('DEV/VRAT/3')).toBe('info')
    expect(toneOf('DEV/VRAT/4')).toBe('danger')
    expect(toneOf('DEV/VRAT/5')).toBe('neutral')
  })

  it('says the last day, and counts several that expire soon', async () => {
    mockApi('get', LIST, [
      makeLabPermit({ permit_reference: 'DEV/VRAT/6', standing: 'expires_soon', expires_on: '2026-10-26', last_valid_day: '2026-10-26', days_left: 0 }),
      makeLabPermit({ permit_reference: 'DEV/VRAT/7', standing: 'expires_soon', expires_on: '2026-10-27', last_valid_day: '2026-10-27', days_left: 1 }),
    ])
    await renderWithProviders(<PermitList labId={LAB_ID} />)
    expect(await screen.findByText('2 permits expire soon.')).toBeInTheDocument()
    expect(rowOf('DEV/VRAT/6')).toHaveTextContent('Last valid day today, 2026-10-26')
    expect(rowOf('DEV/VRAT/7')).toHaveTextContent('Last valid day 2026-10-27, in 1 day')
  })

  it('offers nothing to change: no button, no link, no field', async () => {
    mockApi('get', LIST, [soon, ended])
    await renderWithProviders(<PermitList labId={LAB_ID} />)
    await screen.findByRole('table', { name: 'Permits' })
    expect(screen.queryAllByRole('button')).toHaveLength(0)
    expect(screen.queryAllByRole('link')).toHaveLength(0)
    expect(screen.queryAllByRole('textbox')).toHaveLength(0)
    // The table scrolls sideways on a narrow screen: a named region a keyboard can reach.
    expect(screen.getByRole('region', { name: 'Permits table' })).toHaveAttribute('tabindex', '0')
  })

  it('says when no permit expires soon, and when the lab has none at all', async () => {
    mockApi('get', LIST, [valid])
    const first = await renderWithProviders(<PermitList labId={LAB_ID} />)
    expect(await screen.findByText('No permit expires soon.')).toBeInTheDocument()
    first.unmount()
    mockApi('get', LIST, [])
    await renderWithProviders(<PermitList labId={LAB_ID} />)
    expect(await screen.findByText('The lab has no permit on record.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('shows loading, then a load error with a retry that loads the list', async () => {
    allowConsole(/API error 500/)
    mockApiError('get', LIST, 500)
    await renderWithProviders(<PermitList labId={LAB_ID} />)
    expect(screen.getByText('Loading the permits…')).toBeInTheDocument()
    expect(await screen.findByText(/Could not load the permits/, {}, { timeout: 5000 })).toBeInTheDocument()
    mockApi('get', LIST, [soon])
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('table', { name: 'Permits' })).toBeInTheDocument()
  })
})
