import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeLab, makeMe, makeReveal, page, problem } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { renderApp } from '@/test/render'

// The reveal log of a lab (#83): the lab gate, the role rule, the filters in the URL and the list.

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const REVEALS = '/api/v1/labs/{public_id}/reveals/'
const PERSON = '00000000-0000-4000-8000-0000000000a1'
const signedIn = (role: 'viewer' | 'technician' | 'curator' | 'manager' = 'manager') => {
  mockApi('get', '/api/v1/auth/me/', makeMe())
  mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: role }))
}
const hana = { public_id: PERSON, username: 'hana', first_name: 'Hana', last_name: 'Holá', erased: false }

afterEach(() => vi.useRealTimers())

describe('the reveal log', { timeout: 20_000 }, () => {
  it('shows a manager who revealed which vial and when, newest first as the server sends them', async () => {
    signedIn()
    mockApi(
      'get',
      REVEALS,
      page([
        makeReveal({ occurred_at: '2026-10-20T08:05:00Z', person: hana, vial_label: 'MYC 42 / 1 / 2' }),
        makeReveal({ occurred_at: '2026-10-19T08:05:00Z', person: { ...hana, public_id: '00000000-0000-4000-8000-0000000000a2', username: 'erased-x', first_name: '', last_name: '', erased: true }, vial_label: 'MYC 42 / 1 / 1' }),
      ]),
    )
    renderApp({ path: `/labs/${LAB_ID}/reveals` })
    expect(await screen.findByRole('heading', { level: 1, name: 'Reveals of Mycology' }, { timeout: 5000 })).toBeInTheDocument()
    const table = await screen.findByRole('table', { name: 'Reveals' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows.map((row) => within(row).getAllByRole('cell')[1]?.textContent)).toEqual(['Hana Holá (hana)Only these', 'Erased person'])
    const [first] = rows
    if (first === undefined) throw new Error('no row')
    expect(within(first).getByRole('link', { name: 'MYC 42 / 1 / 2' })).toHaveAttribute('href', expect.stringContaining('/material?vial='))
    expect(within(first).getByText(new Date('2026-10-20T08:05:00Z').toLocaleString('sv', { dateStyle: 'short', timeStyle: 'short' }))).toHaveAttribute('datetime', '2026-10-20T08:05:00Z')
  })

  it('renders no location, even if an answer carried one', async () => {
    signedIn()
    // Not what the server sends: a row with place fields added, to prove the screen names only
    // the fields it knows.
    const leaking = { ...makeReveal({ person: hana, vial_label: 'MYC 42 / 1 / 2' }), location: { path: ['Freezer Secret', 'Rack 9', 'Box Hidden'], label: 'C7' }, box_name: 'Box Hidden' }
    mockApi('get', REVEALS, page([leaking]))
    renderApp({ path: `/labs/${LAB_ID}/reveals` })
    await screen.findByRole('table', { name: 'Reveals' }, { timeout: 5000 })
    const main = screen.getByRole('main')
    for (const text of ['Freezer Secret', 'Rack 9', 'Box Hidden', 'C7']) expect(main).not.toHaveTextContent(text)
  })

  it.each(['viewer', 'technician', 'curator'] as const)('tells a %s that only managers see it, and shows no list', async (role) => {
    signedIn(role)
    mockApiError('get', REVEALS, 403, problem(403))
    renderApp({ path: `/labs/${LAB_ID}/reveals` })
    expect(await screen.findByText('Only managers see who revealed regulated locations.', {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByRole('form', { name: 'Filter reveals' })).not.toBeInTheDocument()
  })

  it('says when nobody has revealed anything', async () => {
    signedIn()
    mockApi('get', REVEALS, page([]))
    renderApp({ path: `/labs/${LAB_ID}/reveals` })
    expect(await screen.findByText('Nobody has revealed where a regulated vial of this lab is stored.', {}, { timeout: 5000 })).toBeInTheDocument()
  })

  it('shows loading, then a retry when the load failed', async () => {
    allowConsole(/API error 500/)
    signedIn()
    mockApiError('get', REVEALS, 500)
    renderApp({ path: `/labs/${LAB_ID}/reveals` })
    expect(await screen.findByText(/Could not load the reveals\./, {}, { timeout: 5000 })).toBeInTheDocument()
    mockApi('get', REVEALS, page([makeReveal({ person: hana })]))
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('table', { name: 'Reveals' }, { timeout: 5000 })).toBeInTheDocument()
  })

  it('This month puts the month in the URL and sends it', async () => {
    vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-02-14T10:00:00') })
    signedIn()
    const calls = mockApi('get', REVEALS, page([makeReveal({ person: hana })]))
    const { router } = renderApp({ path: `/labs/${LAB_ID}/reveals` })
    await screen.findByRole('table', { name: 'Reveals' }, { timeout: 5000 })
    await userEvent.setup().click(screen.getByRole('button', { name: 'This month' }))
    await waitFor(() => expect(router.state.location.search).toEqual({ since: '2026-02-01', until: '2026-02-28' }))
    await waitFor(() => expect(calls.at(-1)?.url.searchParams.get('since')).toBe('2026-02-01'))
    expect(calls.at(-1)?.url.searchParams.get('until')).toBe('2026-02-28')
    expect(screen.getByRole('textbox', { name: 'From' })).toHaveValue('2026-02-01')
  })

  it('applies typed days, refuses a wrong one at the field, and clears', async () => {
    signedIn()
    const calls = mockApi('get', REVEALS, page([makeReveal({ person: hana })]))
    const { router } = renderApp({ path: `/labs/${LAB_ID}/reveals` })
    await screen.findByRole('table', { name: 'Reveals' }, { timeout: 5000 })
    const user = userEvent.setup()
    const from = screen.getByRole('textbox', { name: 'From' })
    await user.type(from, '1.10.2026')
    await user.click(screen.getByRole('button', { name: 'Show' }))
    expect(from).toHaveAccessibleDescription('YYYY-MM-DD Enter a day as YYYY-MM-DD.')
    expect(from).toHaveFocus()
    expect(router.state.location.search).toEqual({})
    await user.clear(from)
    await user.type(from, '2026-10-01')
    await user.type(screen.getByRole('textbox', { name: 'To' }), '2026-10-15{Enter}')
    await waitFor(() => expect(router.state.location.search).toEqual({ since: '2026-10-01', until: '2026-10-15' }))
    await waitFor(() => expect(calls.at(-1)?.url.searchParams.get('until')).toBe('2026-10-15'))
    await user.click(screen.getByRole('button', { name: 'Clear filters' }))
    await waitFor(() => expect(router.state.location.search).toEqual({}))
    expect(from).toHaveValue('')
  })

  it('narrows to one person from a row and back to everyone', async () => {
    signedIn()
    const calls = mockApi('get', REVEALS, page([makeReveal({ person: hana })]))
    const { router } = renderApp({ path: `/labs/${LAB_ID}/reveals` })
    await screen.findByRole('table', { name: 'Reveals' }, { timeout: 5000 })
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Only the reveals of Hana Holá (hana)' }))
    await waitFor(() => expect(router.state.location.search).toEqual({ person: PERSON }))
    await waitFor(() => expect(calls.at(-1)?.url.searchParams.get('person')).toBe(PERSON))
    expect(await screen.findByText(/The reveals of Hana Holá \(hana\)\./)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Only the reveals of/ })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Show everyone' }))
    await waitFor(() => expect(router.state.location.search).toEqual({}))
  })

  it('says when no reveal matches, and clears the filters', async () => {
    signedIn()
    mockApi('get', REVEALS, page([]))
    const { router } = renderApp({ path: `/labs/${LAB_ID}/reveals?since=2026-10-01` })
    expect(await screen.findByText(/No reveal matches these filters\./, {}, { timeout: 5000 })).toBeInTheDocument()
    await userEvent.setup().click(within(screen.getByText(/No reveal matches/)).getByRole('button', { name: 'Clear filters' }))
    await waitFor(() => expect(router.state.location.search).toEqual({}))
  })
})
